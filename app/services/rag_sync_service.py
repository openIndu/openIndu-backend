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


# Chunking parameters — MUST match scripts/offline_embed.py's CHUNK_SIZE_TOKENS /
# CHUNK_OVERLAP_TOKENS so offline-produced vectors are indistinguishable from
# scheduler-produced ones. Token-based (via the real BGE-M3 tokenizer), not
# char-based — see prod/rag-optimization-design.md §5 for the industry-guidance
# research and the scripts/rag_chunk_pilot.py empirical comparison behind these
# two numbers.
CHUNK_SIZE_TOKENS = 400
CHUNK_OVERLAP_TOKENS = 50
# Milvus's `text` VARCHAR(2048) is enforced in UTF-8 BYTES by pymilvus, not
# characters — token count alone doesn't bound this: parameter/register
# tables (common in these PLC manuals) tokenize very efficiently (many chars
# per token), so a token-budget-only chunk can balloon past the byte limit
# well before it hits the token cap. Cap by BOTH; whichever is hit first ends
# the chunk. Margin under 2048 leaves room for the odd multi-byte char at the
# boundary that a byte-exact cap could still trip.
CHUNK_MAX_BYTES = 2000


def _tail_by_tokens(text: str, tokenizer, target_tokens: int) -> str:
    """Longest suffix of `text` whose token count doesn't exceed target_tokens."""
    if target_tokens <= 0 or not text:
        return ""
    lo, hi, best = 0, len(text), ""
    while lo <= hi:
        mid = (lo + hi) // 2
        suffix = text[-mid:] if mid > 0 else ""
        n = len(tokenizer.encode(suffix)) if suffix else 0
        if n <= target_tokens:
            best = suffix
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def _fits_bytes(s: str, max_bytes: int) -> bool:
    return len(s.encode("utf-8")) <= max_bytes


def _explode_oversized(paragraphs: list[str], max_bytes: int) -> list[str]:
    """Hard-split any single paragraph whose byte length alone exceeds max_bytes.

    Rare: PDF text extraction occasionally yields one very long unbroken line
    (e.g. a wide parameter-table row with no internal newline). Doing this up
    front guarantees every paragraph handed to the merge loop is individually
    safe, so the loop only has to worry about merge-time overflow.
    """
    out = []
    for p in paragraphs:
        text = p
        while not _fits_bytes(text, max_bytes):
            lo, hi, cut = 1, len(text), 1
            while lo <= hi:
                mid = (lo + hi) // 2
                if _fits_bytes(text[:mid], max_bytes):
                    cut = mid
                    lo = mid + 1
                else:
                    hi = mid - 1
            out.append(text[:cut])
            text = text[cut:]
        if text:
            out.append(text)
    return out


def scan_documents(db: Session) -> list[dict]:
    """List all PDFs from storage and compare with the documents table.

    Returns a list of dicts with shape:
        {"action": "add"|"update"|"delete", "document": Document | None, "oss_key": str}
    """
    # 1. Collect storage objects under documents/ prefix
    storage_objects: dict[str, dict] = {}
    for obj in storage_service.list_objects(settings.OSS_DOC_PREFIX):
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

    # 3. Chunk text (paragraph-merge, sized by real token count via the BGE-M3
    # tokenizer — see CHUNK_SIZE_TOKENS above). Model is loaded here (rather
    # than at step 4) because chunking now needs its tokenizer; the singleton
    # is cached so this doesn't add a second load.
    model = _get_embedding_model()
    tokenizer = model.tokenizer
    chunks: list[dict] = []
    chunk_id = 0

    for page_info in pages_text:
        text = page_info["text"]
        page = page_info["page"]
        # Split into paragraphs first, then merge into chunks. Bounded by BOTH
        # token count (semantic sizing) and CHUNK_MAX_BYTES (safety net against
        # Milvus's byte-counted VARCHAR limit — see CHUNK_MAX_BYTES above).
        paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
        paragraphs = _explode_oversized(paragraphs, CHUNK_MAX_BYTES)
        current_chunk, current_tokens = "", 0
        for para in paragraphs:
            para_tokens = len(tokenizer.encode(para))
            candidate = (current_chunk + " " + para).strip() if current_chunk else para
            if current_tokens + para_tokens <= CHUNK_SIZE_TOKENS and _fits_bytes(candidate, CHUNK_MAX_BYTES):
                current_chunk = candidate
                current_tokens += para_tokens
            else:
                if current_chunk:
                    chunks.append({
                        "text": current_chunk,
                        "page": page,
                        "chunk_id": chunk_id,
                    })
                    chunk_id += 1
                    overlap_text = _tail_by_tokens(current_chunk, tokenizer, CHUNK_OVERLAP_TOKENS)
                    new_start = (overlap_text + " " + para).strip() if overlap_text else para
                    if not _fits_bytes(new_start, CHUNK_MAX_BYTES):
                        new_start = para  # drop overlap rather than risk overflow — overlap has ~zero measured benefit anyway (design doc §5.3)
                    current_chunk = new_start
                    current_tokens = len(tokenizer.encode(current_chunk))
                else:
                    current_chunk, current_tokens = para, para_tokens
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

    # 4. Generate embeddings (reuse global singleton model loaded in step 3)
    texts = [c["text"] for c in chunks]
    # batch_size=64 for 6GB GPU VRAM (RTX 3060); larger values may cause
    # GPU memory swapping, making encoding extremely slow or stalled.
    embeddings = model.encode(texts, normalize_embeddings=True, batch_size=64)
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
