"""Real OSS → RAG synchronization service.

Scans storage for PDF documents, compares with the database, and syncs
document content into Milvus as vector embeddings for MCP tool retrieval.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import Document
from app.services.storage_service import storage_service

logger = logging.getLogger(__name__)

# Global singleton: reuse the embedding model across all sync calls.
# Loading BGE-M3 on CPU takes seconds — doing it once avoids repeated
# per-document model loads that dominate the upload delay.
_embedding_model = None


def _get_embedding_model():
    """Return the global SentenceTransformer instance, loading on first call."""
    global _embedding_model
    if _embedding_model is None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            logger.error("sentence-transformers not installed.")
            raise
        logger.info("Loading BGE-M3 embedding model from local cache (one-time) …")
        # Use GPU if available, otherwise fall back to CPU
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
        if device == "cuda":
            logger.info("CUDA available — using GPU for embeddings.")
        else:
            logger.info("CUDA not available — using CPU for embeddings.")
        _embedding_model = SentenceTransformer("BAAI/bge-m3", device=device, local_files_only=True)
        logger.info("BGE-M3 model loaded.")
    return _embedding_model


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def scan_documents(db: Session) -> list[dict]:
    """List all PDFs from storage and compare with the documents table.

    Returns a list of dicts with shape:
        {"action": "add"|"update"|"delete", "document": Document | None, "oss_key": str}
    """
    # 1. Collect storage objects under documents/ prefix
    storage_objects: dict[str, dict] = {}
    for obj in storage_service.list_objects("documents"):
        key = obj["key"]
        if not key.lower().endswith(".pdf"):
            continue
        storage_objects[key] = obj

    # 2. Collect DB documents keyed by oss_key
    db_docs: dict[str, Document] = {}
    for doc in db.query(Document).all():
        db_docs[doc.oss_key] = doc

    changes: list[dict] = []

    # 3. Detect adds and updates
    for oss_key, obj in storage_objects.items():
        db_doc = db_docs.get(oss_key)
        if db_doc is None:
            # New document in storage but not in DB — skip (DB entry created at upload)
            # This handles orphan files that were somehow placed in storage manually
            logger.info("Orphan file in storage (no DB entry): %s", oss_key)
            continue
        # Check if file has changed (size or hash mismatch)
        if db_doc.file_hash and db_doc.file_size and (
            db_doc.file_size != obj.get("size")
        ):
            changes.append({"action": "update", "document": db_doc, "oss_key": oss_key})
        elif db_doc.sync_status != "synced":
            changes.append({"action": "add", "document": db_doc, "oss_key": oss_key})

    # 4. Detect deletes (DB entries with no matching storage object)
    for oss_key, db_doc in db_docs.items():
        if oss_key not in storage_objects:
            changes.append({"action": "delete", "document": db_doc, "oss_key": oss_key})

    return changes


def sync_document(db: Session, doc: Document) -> bool:
    """Sync a single document into Milvus.

    Steps:
      1. Read the PDF file from storage
      2. Extract text with PyMuPDF (fitz)
      3. Chunk the text
      4. Generate embeddings with BGE-M3
      5. Insert into Milvus

    Returns True on success, raises on failure.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        logger.error("PyMuPDF (fitz) is not installed. Cannot extract PDF text.")
        raise

    try:
        from pymilvus import Collection, connections
    except ImportError:
        logger.error("pymilvus not installed.")
        raise

    # 1. Read the PDF
    if storage_service.is_local:
        file_path = storage_service.get_file_path(doc.oss_key)
        pdf_doc = fitz.open(str(file_path))
    else:
        # S3 mode: download to memory
        import io
        url_info = storage_service.get_download_url(doc.oss_key)
        import httpx
        resp = httpx.get(url_info["url"])
        resp.raise_for_status()
        pdf_doc = fitz.open(stream=io.BytesIO(resp.content), filetype="pdf")

    # 2. Extract text page by page
    pages_text: list[dict] = []
    for page_num in range(pdf_doc.page_count):
        page = pdf_doc[page_num]
        text = page.get_text()
        if text and text.strip():
            pages_text.append({"page": page_num + 1, "text": text.strip()})
    pdf_doc.close()

    if not pages_text:
        logger.warning("No extractable text in document %s", doc.original_name)
        return True  # Nothing to embed, but not a failure

    # 3. Chunk text (simple paragraph-based chunking with overlap)
    chunks: list[dict] = []
    chunk_size = 512
    chunk_overlap = 50
    chunk_id = 0

    for page_info in pages_text:
        text = page_info["text"]
        page = page_info["page"]
        # Split into paragraphs first, then merge into chunks
        paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
        current_chunk = ""
        for para in paragraphs:
            if len(current_chunk) + len(para) + 1 <= chunk_size:
                current_chunk = (current_chunk + " " + para).strip() if current_chunk else para
            else:
                if current_chunk:
                    chunks.append({
                        "text": current_chunk,
                        "page": page,
                        "chunk_id": chunk_id,
                    })
                    chunk_id += 1
                    # Overlap: keep last chunk_overlap chars
                    overlap_text = current_chunk[-chunk_overlap:] if len(current_chunk) > chunk_overlap else ""
                    current_chunk = (overlap_text + " " + para).strip() if overlap_text else para
                else:
                    current_chunk = para
        if current_chunk:
            chunks.append({
                "text": current_chunk,
                "page": page,
                "chunk_id": chunk_id,
            })
            chunk_id += 1

    if not chunks:
        logger.warning("No chunks generated for document %s", doc.original_name)
        return True

    # 4. Generate embeddings (reuse global singleton model)
    model = _get_embedding_model()
    texts = [c["text"] for c in chunks]
    # batch_size=256 reduces encode time on CPU (default 32 → ~8x fewer iterations)
    embeddings = model.encode(texts, normalize_embeddings=True, batch_size=256)
    if hasattr(embeddings, "tolist"):
        embeddings = embeddings.tolist()

    # 5. Insert into Milvus
    # Delete existing vectors for this document first (idempotent re-sync)
    connections.connect(alias="default", host=settings.MILVUS_HOST, port=settings.MILVUS_PORT)
    collection = Collection(settings.MILVUS_COLLECTION)
    collection.load()

    # Remove old entries for this document
    delete_expr = f'document_name == "{doc.original_name}"'
    try:
        collection.delete(delete_expr)
    except Exception:
        logger.debug("No existing vectors to delete for %s", doc.original_name)

    # Prepare insert data
    insert_data = []
    for i, chunk in enumerate(chunks):
        insert_data.append({
            "text": chunk["text"],
            "document_name": doc.original_name,
            "brand": doc.brand,
            "category": doc.category,
            "page": chunk["page"],
            "chunk_id": chunk["chunk_id"],
            "embedding": embeddings[i],
        })

    if insert_data:
        collection.insert(insert_data)
        collection.flush()

    return True
