"""Document CRUD and presigned download-link API."""
import logging
from datetime import date, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.dependencies import get_db, require_admin, require_member
from app.core.utils import ok
from app.models.document import Document
from app.models.download_log import DownloadLog
from app.models.resource_tag import ResourceTag
from app.models.user import User
from app.services.rag_sync_service import sync_document
from app.services.storage_service import storage_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents")


def _valid_values(db: Session, tag_type: str) -> list[str]:
    return [t.value for t in db.query(ResourceTag).filter(ResourceTag.type == tag_type, ResourceTag.is_active == True).all()]  # noqa: E712


def _validate_doc_series(db: Session, brand: str, category: str, series: str | None) -> None:
    if not series:
        return
    exists = db.query(ResourceTag).filter(
        ResourceTag.type == "doc_series",
        ResourceTag.value == series,
        ResourceTag.brand_value == brand,
        ResourceTag.parent_value == category,
        ResourceTag.is_active == True,  # noqa: E712
    ).first()
    if not exists:
        raise HTTPException(400, "无效系列")


def _check_document_daily_limit(db: Session, user: User) -> None:
    # Admins bypass the 5/day cap — they curate the catalog and shouldn't be
    # locked out while reviewing uploads or fielding member tickets.
    if user.role == "admin":
        return
    today_start = datetime.combine(date.today(), datetime.min.time())
    count = db.query(DownloadLog).filter(
        DownloadLog.user_id == user.id,
        DownloadLog.resource_type == "document",
        DownloadLog.created_at >= today_start,
    ).count()
    if count >= settings.DOWNLOAD_DAILY_LIMIT:
        raise HTTPException(status_code=429, detail="今日文档下载次数已用完（5次/天）")


def _check_document_preview_daily_limit(db: Session, user: User) -> None:
    # Preview has its OWN daily quota, separate from downloads — in-page reading
    # shouldn't consume the 5/day download budget. It's still capped (and logged
    # under a distinct resource_type) so preview can't be used to bypass the
    # download limit, since the inline file can still be saved. Admins are exempt.
    if user.role == "admin":
        return
    today_start = datetime.combine(date.today(), datetime.min.time())
    count = db.query(DownloadLog).filter(
        DownloadLog.user_id == user.id,
        DownloadLog.resource_type == "document_preview",
        DownloadLog.created_at >= today_start,
    ).count()
    if count >= settings.PREVIEW_DAILY_LIMIT:
        raise HTTPException(status_code=429, detail=f"今日文档预览次数已用完（{settings.PREVIEW_DAILY_LIMIT}次/天）")


def _file_size(file: UploadFile) -> int:
    """Return upload size without loading the file into memory."""
    if file.size is not None:
        return file.size
    stream = file.file
    pos = stream.tell()
    stream.seek(0, 2)
    size = stream.tell()
    stream.seek(pos)
    return size


def _sync_uploaded_document(doc_id: int):
    db = None
    try:
        db = SessionLocal()
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if not doc:
            return
        doc.sync_status = "syncing"
        db.commit()
        sync_document(db, doc)
        doc.sync_status = "synced"
        doc.sync_time = datetime.utcnow()
        db.commit()
    except Exception as exc:
        logger.error("Document %s background sync failed: %s", doc_id, exc)
        if db:
            try:
                db.rollback()
                doc = db.query(Document).filter(Document.id == doc_id).first()
                if doc:
                    doc.sync_status = "failed"
                    doc.sync_time = datetime.utcnow()
                    db.commit()
            except Exception as inner_exc:
                logger.error("Failed to update sync_status for doc %s: %s", doc_id, inner_exc)
    finally:
        if db:
            db.close()


def client_ip(request: Request) -> str | None:
    from app.core.utils import real_client_ip
    return real_client_ip(request)


@router.get("")
async def list_documents(
    brand: str | None = None,
    category: str | None = None,
    series: str | None = None,
    keyword: str | None = None,
    published_only: bool = False,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    sort_by: str = Query("upload_time", regex="^(file_size|upload_time|download_count)$"),
    sort_order: str = Query("desc", regex="^(asc|desc)$"),
    db: Session = Depends(get_db)
):
    q = db.query(Document)
    if published_only:
        q = q.filter(Document.is_published == True)  # noqa: E712
    if brand:
        q = q.filter(Document.brand == brand)
    if category:
        q = q.filter(Document.category == category)
    if series:
        q = q.filter(Document.series == series)
    if keyword:
        q = q.filter(Document.original_name.ilike(f"%{keyword}%"))
    total = q.count()

    # Apply sorting
    sort_column = {
        "file_size": Document.file_size,
        "upload_time": Document.upload_time,
        "download_count": Document.download_count
    }[sort_by]

    if sort_order == "asc":
        q = q.order_by(sort_column.asc())
    else:
        q = q.order_by(sort_column.desc())

    items = [d.to_dict() for d in q.offset((page - 1) * size).limit(size).all()]
    return ok({"items": items, "total": total, "page": page, "size": size})


@router.post("/upload")
async def upload_document(file: UploadFile = File(...), brand: str = Form(...), category: str = Form(...), series: str = Form(""), description: str = Form(""), db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    # 1. 所有前置校验 — 失败时不产生副作用
    brands = _valid_values(db, "doc_brand")
    categories = _valid_values(db, "doc_category")
    if brand not in brands:
        raise HTTPException(400, "无效品牌")
    if category not in categories:
        raise HTTPException(400, "无效分类")
    _validate_doc_series(db, brand, category, series or None)
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(415, "仅支持 PDF 文件")
    if _file_size(file) > settings.DOCUMENT_MAX_SIZE_MB * 1024 * 1024:
        raise HTTPException(413, "文件大小超过限制")

    # 2. 先上传文件到存储 — 流式 + 线程池卸载，避免阻塞事件循环
    meta = await run_in_threadpool(storage_service.upload_file, file.file, file.filename, f"{settings.OSS_DOC_PREFIX}/{brand}", file.content_type or "application/pdf")

    # 3. 然后写入 DB — DB 失败时删除已上传的文件
    doc = Document(filename=meta["filename"], original_name=file.filename, brand=brand, category=category, series=series or None, file_size=meta["file_size"], file_hash=meta["file_hash"], oss_key=meta["oss_key"], description=description)
    try:
        db.add(doc)
        db.commit()
        db.refresh(doc)
    except Exception:
        # 回滚：删除已存在的文件，避免出现 OSS 上的幽灵文件
        await run_in_threadpool(storage_service.delete_file, meta["oss_key"])
        raise

    return ok(doc.to_dict(), "上传成功")


@router.get("/brands/list")
async def brands(db: Session = Depends(get_db)):
    return ok(_valid_values(db, "doc_brand"))


@router.get("/categories/list")
async def categories(db: Session = Depends(get_db)):
    values = _valid_values(db, "doc_category")
    return ok(values)


@router.get("/{doc_id}")
async def get_document(doc_id: int, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "文档不存在")
    return ok(doc.to_dict())


@router.get("/{doc_id}/download-link")
async def get_document_download_link(doc_id: int, request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_member)):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    _check_document_daily_limit(db, current_user)
    doc.download_count = (doc.download_count or 0) + 1
    db.add(DownloadLog(user_id=current_user.id, resource_type="document", resource_id=doc_id, ip_address=client_ip(request)))
    db.commit()
    signed_url = storage_service.get_download_url(doc.oss_key)
    return ok({"download_url": signed_url["url"], "expires_in": signed_url["expires_in"], "filename": doc.original_name})


@router.get("/{doc_id}/preview-link")
async def get_document_preview_link(doc_id: int, request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_member)):
    """Return an inline presigned URL so the browser renders the PDF in‑page.

    Preview uses a SEPARATE daily quota (``PREVIEW_DAILY_LIMIT``) and does NOT
    consume the download budget nor bump ``download_count`` — previewing is not a
    download. The preview is logged under ``resource_type=document_preview`` so it
    is counted independently and still capped (preview can't bypass the limit).
    """
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    _check_document_preview_daily_limit(db, current_user)
    db.add(DownloadLog(user_id=current_user.id, resource_type="document_preview", resource_id=doc_id, ip_address=client_ip(request)))
    db.commit()
    inline_url = storage_service.get_preview_url(doc.oss_key)
    return ok({"preview_url": inline_url["url"], "expires_in": inline_url["expires_in"], "filename": doc.original_name})


class UpdateDocumentBody(BaseModel):
    original_name: str | None = None
    brand: str | None = None
    category: str | None = None
    series: str | None = None
    description: str | None = None


class BulkPublishDocumentsBody(BaseModel):
    ids: list[int] | None = None
    brand: str | None = None
    category: str | None = None
    series: str | None = None
    keyword: str | None = None
    publish: bool = True


@router.patch("/publish/bulk")
async def bulk_publish_documents(body: BulkPublishDocumentsBody, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    q = db.query(Document)
    if body.ids is not None:
        if not body.ids:
            raise HTTPException(400, "请选择要操作的文档")
        q = q.filter(Document.id.in_(body.ids))
    else:
        if body.brand:
            q = q.filter(Document.brand == body.brand)
        if body.category:
            q = q.filter(Document.category == body.category)
        if body.series:
            q = q.filter(Document.series == body.series)
        if body.keyword:
            q = q.filter(Document.original_name.ilike(f"%{body.keyword}%"))
    # Only flip documents whose current state differs from the target.
    docs = q.filter(Document.is_published == (not body.publish)).all()
    for doc in docs:
        doc.is_published = body.publish
    db.commit()
    return ok({"count": len(docs), "publish": body.publish}, "发布成功" if body.publish else "取消发布成功")


@router.patch("/{doc_id}")
async def update_document(doc_id: int, body: UpdateDocumentBody, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "文档不存在")
    if body.brand is not None:
        if body.brand not in _valid_values(db, "doc_brand"):
            raise HTTPException(400, "无效品牌")
        doc.brand = body.brand
        if body.series is None:
            doc.series = None
    if body.category is not None:
        if body.category not in _valid_values(db, "doc_category"):
            raise HTTPException(400, "无效分类")
        doc.category = body.category
        if body.series is None:
            doc.series = None
    if body.series is not None:
        _validate_doc_series(db, doc.brand, doc.category, body.series or None)
        doc.series = body.series or None
    if body.original_name is not None:
        if not body.original_name.strip():
            raise HTTPException(400, "文档名不能为空")
        doc.original_name = body.original_name.strip()
    if body.description is not None:
        doc.description = body.description
    db.commit()
    db.refresh(doc)
    return ok(doc.to_dict(), "更新成功")


@router.patch("/{doc_id}/publish")
async def toggle_publish(doc_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "文档不存在")
    doc.is_published = not doc.is_published
    db.commit()
    db.refresh(doc)
    return ok(doc.to_dict(), "发布状态已更新")


@router.post("/{doc_id}/sync")
async def sync_document_endpoint(doc_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    # When RAG sync is disabled this backend must not run BGE-M3 embedding —
    # the node is resource-constrained on purpose. Syncs are produced offline
    # and pushed to Milvus separately. Reject manual triggers too, not just
    # the scheduler, so a button click can't quietly spin up the embedding
    # stack here. 503 = "this capability is intentionally off on this host".
    if not settings.RAG_SYNC_ENABLED:
        raise HTTPException(503, "本环境已关闭 RAG 同步（RAG_SYNC_ENABLED=false），请在离线环境同步后导入向量")
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "文档不存在")
    if doc.sync_status == "syncing":
        raise HTTPException(409, "文档正在同步中，请稍后再试")
    doc.sync_status = "syncing"
    db.commit()
    db.refresh(doc)
    background_tasks.add_task(_sync_uploaded_document, doc_id)
    return ok(doc.to_dict(), "同步已启动")


@router.delete("/{doc_id}")
async def delete_document(doc_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "文档不存在")
    storage_service.delete_file(doc.oss_key)
    db.delete(doc)
    db.commit()
    return ok(message="删除成功")
