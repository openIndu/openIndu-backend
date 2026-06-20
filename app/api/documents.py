"""Document CRUD and presigned download-link API."""
import logging
from datetime import date, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, UploadFile
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.dependencies import get_db, require_admin, require_member
from app.models.document import Document
from app.models.download_log import DownloadLog
from app.models.user import User
from app.services.rag_sync_service import sync_document
from app.services.storage_service import storage_service
from app.services.rag_sync_service import sync_document

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents")
BRANDS = ["siemens", "mitsubishi", "omron", "keyence", "inovance"]
CATEGORIES = ["plc-manual", "hardware-manual", "driver-manual", "hmi-manual", "software-manual", "best-practice", "electrical-standard", "other"]


def ok(data=None, message="操作成功"):
    return {"code": 200, "message": message, "data": data or {}}


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
async def list_documents(brand: str | None = None, category: str | None = None, keyword: str | None = None, page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    q = db.query(Document)
    if brand:
        q = q.filter(Document.brand == brand)
    if category:
        q = q.filter(Document.category == category)
    if keyword:
        q = q.filter(Document.original_name.ilike(f"%{keyword}%"))
    total = q.count()
    items = [d.to_dict() for d in q.order_by(Document.upload_time.desc()).offset((page - 1) * size).limit(size).all()]
    return ok({"items": items, "total": total, "page": page, "size": size})


@router.post("/upload")
async def upload_document(background_tasks: BackgroundTasks, file: UploadFile = File(...), brand: str = Form(...), category: str = Form(...), description: str = Form(""), db: Session = Depends(get_db), admin: User = Depends(require_admin)):
<<<<<<< HEAD
    if brand not in BRANDS: raise HTTPException(400, "无效品牌")
    if category not in CATEGORIES: raise HTTPException(400, "无效分类")
    if not file.filename or not file.filename.lower().endswith(".pdf"): raise HTTPException(415, "仅支持 PDF 文件")
=======
    if brand not in BRANDS:
        raise HTTPException(400, "无效品牌")
    if category not in CATEGORIES:
        raise HTTPException(400, "无效分类")
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(415, "仅支持 PDF 文件")
>>>>>>> origin/main
    content = await file.read()
    if len(content) > settings.DOCUMENT_MAX_SIZE_MB * 1024 * 1024:
        raise HTTPException(413, "文件大小超过限制")
    meta = storage_service.upload_file(content, file.filename, f"documents/{brand}", file.content_type or "application/pdf")
    doc = Document(filename=meta["filename"], original_name=file.filename, brand=brand, category=category, file_size=meta["file_size"], file_hash=meta["file_hash"], oss_key=meta["oss_key"], description=description)
<<<<<<< HEAD
    db.add(doc); db.commit(); db.refresh(doc)
=======
    db.add(doc)
    db.commit()
    db.refresh(doc)
>>>>>>> origin/main
    background_tasks.add_task(_sync_uploaded_document, doc.id)
    return ok(doc.to_dict(), "上传成功，同步已自动启动")


@router.get("/brands/list")
async def brands():
    return ok(BRANDS)


@router.get("/categories/list")
async def categories():
    return ok(CATEGORIES)


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


@router.delete("/{doc_id}")
async def delete_document(doc_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(404, "文档不存在")
    storage_service.delete_file(doc.oss_key)
    db.delete(doc)
    db.commit()
    return ok(message="删除成功")
