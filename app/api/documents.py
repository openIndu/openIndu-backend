"""Document CRUD and presigned download-link API."""
import logging
from datetime import date, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.dependencies import get_db, require_admin, require_member
from app.models.document import Document
from app.models.download_log import DownloadLog
from app.models.resource_tag import ResourceTag
from app.models.user import User
from app.services.rag_sync_service import sync_document
from app.services.storage_service import storage_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents")


def ok(data=None, message="操作成功"):
    return {"code": 200, "message": message, "data": data or {}}


def _valid_values(db: Session, tag_type: str) -> list[str]:
    return [t.value for t in db.query(ResourceTag).filter(ResourceTag.type == tag_type, ResourceTag.is_active == True).all()]  # noqa: E712


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
    forwarded = request.headers.get("x-forwarded-for")
    return forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else None)


@router.get("")
async def list_documents(brand: str | None = None, category: str | None = None, series: str | None = None, keyword: str | None = None, published_only: bool = False, page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
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
    items = [d.to_dict() for d in q.order_by(Document.upload_time.desc()).offset((page - 1) * size).limit(size).all()]
    return ok({"items": items, "total": total, "page": page, "size": size})


@router.post("/upload")
async def upload_document(file: UploadFile = File(...), brand: str = Form(...), category: str = Form(...), series: str = Form(""), description: str = Form(""), db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    brands = _valid_values(db, "brand")
    categories = _valid_values(db, "doc_category")
    if brand not in brands:
        raise HTTPException(400, "无效品牌")
    if category not in categories:
        raise HTTPException(400, "无效分类")
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(415, "仅支持 PDF 文件")
    content = await file.read()
    if len(content) > settings.DOCUMENT_MAX_SIZE_MB * 1024 * 1024:
        raise HTTPException(413, "文件大小超过限制")
    meta = storage_service.upload_file(content, file.filename, f"{settings.OSS_DOC_PREFIX}/{brand}", file.content_type or "application/pdf")
    doc = Document(filename=meta["filename"], original_name=file.filename, brand=brand, category=category, series=series or None, file_size=meta["file_size"], file_hash=meta["file_hash"], oss_key=meta["oss_key"], description=description)
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return ok(doc.to_dict(), "上传成功")


@router.get("/brands/list")
async def brands(db: Session = Depends(get_db)):
    values = _valid_values(db, "brand")
    return ok(values)


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
    today_start = datetime.combine(date.today(), datetime.min.time())
    today_count = db.query(DownloadLog).filter(DownloadLog.user_id == current_user.id, DownloadLog.resource_type == "document", DownloadLog.created_at >= today_start).count()
    if today_count >= settings.DOWNLOAD_DAILY_LIMIT:
        raise HTTPException(status_code=429, detail="今日文档下载次数已用完（5次/天）")
    doc.download_count = (doc.download_count or 0) + 1
    db.add(DownloadLog(user_id=current_user.id, resource_type="document", resource_id=doc_id, ip_address=client_ip(request)))
    db.commit()
    signed_url = storage_service.get_download_url(doc.oss_key)
    return ok({"download_url": signed_url["url"], "expires_in": signed_url["expires_in"], "filename": doc.original_name})


class UpdateDocumentBody(BaseModel):
    original_name: str | None = None
    brand: str | None = None
    category: str | None = None
    series: str | None = None
    description: str | None = None


@router.patch("/{doc_id}")
async def update_document(doc_id: int, body: UpdateDocumentBody, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "文档不存在")
    if body.brand is not None:
        if body.brand not in _valid_values(db, "brand"):
            raise HTTPException(400, "无效品牌")
        doc.brand = body.brand
    if body.category is not None:
        if body.category not in _valid_values(db, "doc_category"):
            raise HTTPException(400, "无效分类")
        doc.category = body.category
        if body.series is None:
            doc.series = None
    if body.series is not None:
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
