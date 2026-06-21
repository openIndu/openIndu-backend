"""Software package and version API."""
from datetime import date, datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.dependencies import get_db, require_admin, require_member
from app.models.download_log import DownloadLog
from app.models.software import Software, SoftwareVersion
from app.models.user import User
from app.services.storage_service import storage_service

router = APIRouter(prefix="/software")
BRANDS = ["siemens", "mitsubishi", "omron", "keyence", "inovance"]
CATEGORIES = ["plc-ide", "hmi-ide", "plc-driver", "utility", "firmware", "other"]
ALLOWED_EXTS = {".zip", ".exe", ".msi", ".rar", ".7z"}


def ok(data=None, message="操作成功"):
    return {"code": 200, "message": message, "data": data or {}}


def _ext(filename: str) -> str:
    return "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _ip(request: Request):
    forwarded = request.headers.get("x-forwarded-for")
    return forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else None)


def _check_daily_limit(db: Session, user: User):
    today_start = datetime.combine(date.today(), datetime.min.time())
    count = db.query(DownloadLog).filter(DownloadLog.user_id == user.id, DownloadLog.resource_type == "software", DownloadLog.created_at >= today_start).count()
    if count >= settings.DOWNLOAD_DAILY_LIMIT:
        raise HTTPException(429, "今日软件下载次数已用完（5次/天）")


@router.get("")
async def list_software(brand: str | None = None, category: str | None = None, keyword: str | None = None, published_only: bool = False, page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    q = db.query(Software).filter(Software.is_active.is_(True))
    if published_only:
        q = q.filter(Software.is_published == True)  # noqa: E712
    if brand: q = q.filter(Software.brand == brand)
    if category: q = q.filter(Software.category == category)
    if keyword: q = q.filter(Software.original_name.ilike(f"%{keyword}%"))
    total = q.count(); items = [s.to_dict() for s in q.order_by(Software.created_at.desc()).offset((page - 1) * size).limit(size).all()]
    return ok({"items": items, "total": total, "page": page, "size": size})


@router.post("/upload")
async def upload_software(file: UploadFile = File(...), brand: str = Form(...), category: str = Form(...), version: str = Form(...), description: str = Form(""), db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    if brand not in BRANDS: raise HTTPException(400, "无效品牌")
    if category not in CATEGORIES: raise HTTPException(400, "无效分类")
    if not file.filename or _ext(file.filename) not in ALLOWED_EXTS: raise HTTPException(415, "不支持的软件包格式")
    content = await file.read()
    if len(content) > settings.SOFTWARE_MAX_SIZE_GB * 1024 * 1024 * 1024: raise HTTPException(413, "文件大小超过限制")
    meta = storage_service.upload_file(content, file.filename, f"software/{brand}", file.content_type)
    sw = Software(filename=meta["filename"], original_name=file.filename, brand=brand, category=category, latest_version=version, description=description)
    db.add(sw); db.flush()
    db.add(SoftwareVersion(software_id=sw.id, version=version, file_size=meta["file_size"], file_hash=meta["file_hash"], oss_key=meta["oss_key"]))
    db.commit(); db.refresh(sw)
    return ok(sw.to_dict(include_versions=True), "上传成功")


@router.get("/brands/list")
async def brands():
    return ok(BRANDS)


@router.get("/categories/list")
async def categories():
    return ok(CATEGORIES)


@router.get("/{software_id}")
async def get_software(software_id: int, db: Session = Depends(get_db)):
    sw = db.query(Software).filter(Software.id == software_id).first()
    if not sw: raise HTTPException(404, "软件不存在")
    return ok(sw.to_dict(include_versions=True))


@router.get("/{software_id}/download-link")
async def download_latest(software_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_member)):
    sw = db.query(Software).filter(Software.id == software_id).first()
    if not sw: raise HTTPException(404, "软件不存在")
    version = db.query(SoftwareVersion).filter(SoftwareVersion.software_id == software_id, SoftwareVersion.is_active.is_(True)).order_by(SoftwareVersion.upload_time.desc()).first()
    if not version: raise HTTPException(404, "软件版本不存在")
    return _download_version(db, sw, version, user, request)


@router.get("/{software_id}/versions/{version_id}/download-link")
async def download_version(software_id: int, version_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_member)):
    sw = db.query(Software).filter(Software.id == software_id).first()
    version = db.query(SoftwareVersion).filter(SoftwareVersion.id == version_id, SoftwareVersion.software_id == software_id).first()
    if not sw or not version: raise HTTPException(404, "软件版本不存在")
    return _download_version(db, sw, version, user, request)


def _download_version(db: Session, sw: Software, version: SoftwareVersion, user: User, request: Request):
    _check_daily_limit(db, user)
    sw.download_count = (sw.download_count or 0) + 1
    version.download_count = (version.download_count or 0) + 1
    db.add(DownloadLog(user_id=user.id, resource_type="software", resource_id=sw.id, ip_address=_ip(request)))
    db.commit()
    url = storage_service.get_download_url(version.oss_key)
    return ok({"download_url": url["url"], "expires_in": url["expires_in"], "filename": sw.original_name, "version": version.version})


@router.post("/{software_id}/versions")
async def add_version(software_id: int, file: UploadFile = File(...), version: str = Form(...), db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    sw = db.query(Software).filter(Software.id == software_id).first()
    if not sw: raise HTTPException(404, "软件不存在")
    if not file.filename or _ext(file.filename) not in ALLOWED_EXTS: raise HTTPException(415, "不支持的软件包格式")
    content = await file.read(); meta = storage_service.upload_file(content, file.filename, f"software/{sw.brand}", file.content_type)
    ver = SoftwareVersion(software_id=sw.id, version=version, file_size=meta["file_size"], file_hash=meta["file_hash"], oss_key=meta["oss_key"])
    sw.latest_version = version
    db.add(ver); db.commit(); db.refresh(ver)
    return ok(ver.to_dict(), "版本已添加")


@router.delete("/{software_id}/versions/{version_id}")
async def delete_version(software_id: int, version_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    ver = db.query(SoftwareVersion).filter(SoftwareVersion.id == version_id, SoftwareVersion.software_id == software_id).first()
    if not ver: raise HTTPException(404, "版本不存在")
    storage_service.delete_file(ver.oss_key); db.delete(ver); db.commit()
    return ok(message="删除成功")


@router.patch("/{software_id}/publish")
async def toggle_publish(software_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    sw = db.query(Software).filter(Software.id == software_id).first()
    if not sw: raise HTTPException(404, "软件不存在")
    sw.is_published = not sw.is_published
    db.commit(); db.refresh(sw)
    return ok(sw.to_dict(), "发布状态已更新")


@router.delete("/{software_id}")
async def delete_software(software_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    sw = db.query(Software).filter(Software.id == software_id).first()
    if not sw: raise HTTPException(404, "软件不存在")
    for ver in sw.versions: storage_service.delete_file(ver.oss_key)
    db.delete(sw); db.commit()
    return ok(message="删除成功")
