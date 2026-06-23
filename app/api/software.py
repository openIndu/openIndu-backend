"""Software package and version API."""
import math
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.dependencies import get_db, require_admin, require_member
from app.core.utils import ok, oss_key_for_upload
from app.models.download_log import DownloadLog
from app.models.resource_tag import ResourceTag
from app.models.software import Software, SoftwareVersion
from app.models.user import User
from app.services.storage_service import storage_service

router = APIRouter(prefix="/software")
ALLOWED_EXTS = {".zip", ".exe", ".msi", ".rar", ".7z"}


def _ext(filename: str) -> str:
    return "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _ip(request: Request):
    forwarded = request.headers.get("x-forwarded-for")
    return forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else None)


def _valid_values(db: Session, tag_type: str) -> list[str]:
    return [t.value for t in db.query(ResourceTag).filter(ResourceTag.type == tag_type, ResourceTag.is_active == True).all()]  # noqa: E712


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


def _check_daily_limit(db: Session, user: User):
    # Admins bypass the 5/day cap — they curate the catalog and shouldn't be
    # locked out while validating uploads or fielding member tickets.
    if user.role == "admin":
        return
    today_start = datetime.combine(date.today(), datetime.min.time())
    count = db.query(DownloadLog).filter(DownloadLog.user_id == user.id, DownloadLog.resource_type == "software", DownloadLog.created_at >= today_start).count()
    if count >= settings.DOWNLOAD_DAILY_LIMIT:
        raise HTTPException(429, "今日软件下载次数已用完（5次/天）")


@router.get("")
async def list_software(brand: str | None = None, category: str | None = None, keyword: str | None = None, published_only: bool = False, expand_versions: bool = False, page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    q = db.query(Software).filter(Software.is_active.is_(True))
    if published_only:
        q = q.filter(Software.is_published == True)  # noqa: E712
    if brand: q = q.filter(Software.brand == brand)
    if category: q = q.filter(Software.category == category)
    if keyword: q = q.filter(Software.original_name.ilike(f"%{keyword}%"))
    total = q.count()
    rows = q.order_by(Software.created_at.desc()).offset((page - 1) * size).limit(size).all()
    if not expand_versions:
        items = [s.to_dict() for s in rows]
        return ok({"items": items, "total": total, "page": page, "size": size})
    # 摊平为「每个版本一行」 — 同一软件的多个版本在 UI 上各占一行。
    # 软件本身的字段（品牌、分类等）被复制到每行，便于前端无脑渲染表格；
    # 同时附上 version_id / version / file_size / oss_key 让操作（下载/删除）能定位到版本。
    items = []
    for s in rows:
        base = s.to_dict()
        if not s.versions:
            items.append(base)
            continue
        for v in sorted(s.versions, key=lambda x: x.upload_time, reverse=True):
            items.append({
                **base,
                "version_id": v.id,
                "version": v.version,
                "latest_version_size": v.file_size,
                "file_hash": v.file_hash,
                "oss_key": v.oss_key,
                "version_upload_time": v.upload_time.isoformat() if v.upload_time else None,
                "version_download_count": v.download_count,
                "is_latest_version": v.version == s.latest_version,
            })
    return ok({"items": items, "total": total, "page": page, "size": size})


@router.post("/upload")
async def upload_software(file: UploadFile = File(...), brand: str = Form(...), category: str = Form(...), version: str = Form(...), description: str = Form(""), db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    # 1. 所有前置校验 — 失败时不产生副作用
    brands = _valid_values(db, "sw_brand")
    categories = _valid_values(db, "sw_category")
    if brand not in brands: raise HTTPException(400, "无效品牌")
    if category not in categories: raise HTTPException(400, "无效分类")
    if not file.filename or _ext(file.filename) not in ALLOWED_EXTS: raise HTTPException(415, "不支持的软件包格式")
    if _file_size(file) > settings.SOFTWARE_MAX_SIZE_GB * 1024 * 1024 * 1024: raise HTTPException(413, "文件大小超过限制")

    # 2. 先上传文件到存储 — 流式 + 线程池卸载，避免阻塞事件循环
    meta = await run_in_threadpool(storage_service.upload_file, file.file, file.filename, f"{settings.OSS_SOFTWARE_PREFIX}/{brand}", file.content_type or "application/octet-stream")

    # 3. 然后写入 DB（两条记录）— DB 失败时删除已上传的文件
    sw = Software(filename=meta["filename"], original_name=file.filename, brand=brand, category=category, latest_version=version, description=description)
    try:
        db.add(sw)
        db.flush()
        db.add(SoftwareVersion(software_id=sw.id, version=version, file_size=meta["file_size"], file_hash=meta["file_hash"], oss_key=meta["oss_key"]))
        db.commit()
        db.refresh(sw)
    except Exception:
        # 回滚：删除已存在的文件，避免出现 OSS 上的幽灵文件
        await run_in_threadpool(storage_service.delete_file, meta["oss_key"])
        raise

    return ok(sw.to_dict(include_versions=True), "上传成功")


# ---------------------------------------------------------------------------
# Direct-to-OSS upload (large software packages, several GB)
#
# Browser uploads the file body straight to OSS via presigned URLs, bypassing
# the backend entirely. The backend only signs the upload and records metadata
# afterwards — no large body passes through FastAPI/nginx, so there is no
# event-loop blocking, no memory pressure, and no nginx body/timeout limits.
# ---------------------------------------------------------------------------

UPLOAD_TOKEN_EXPIRE_HOURS = 2


class UploadInitBody(BaseModel):
    filename: str
    brand: str
    category: str
    version: str
    description: str = ""
    content_type: str | None = None
    size: int  # bytes
    software_id: int | None = None  # 给已有软件加版本时传入


class UploadPartResult(BaseModel):
    part_number: int
    etag: str


class UploadCompleteBody(BaseModel):
    token: str
    parts: list[UploadPartResult] | None = None
    file_hash: str | None = None


class UploadAbortBody(BaseModel):
    token: str


def _decode_upload_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as exc:
        raise HTTPException(400, f"无效或过期的上传凭证: {exc}")


@router.post("/upload/init")
async def upload_init(body: UploadInitBody, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    # 1. 校验 — 失败时不产生任何 OSS 副作用
    if body.software_id:
        existing_sw = db.query(Software).filter(Software.id == body.software_id).first()
        if not existing_sw: raise HTTPException(400, "软件不存在")
        brand = existing_sw.brand
        category = existing_sw.category
    else:
        brands = _valid_values(db, "sw_brand")
        categories = _valid_values(db, "sw_category")
        if body.brand not in brands: raise HTTPException(400, "无效品牌")
        if body.category not in categories: raise HTTPException(400, "无效分类")
        brand = body.brand
        category = body.category
    if not body.filename or _ext(body.filename) not in ALLOWED_EXTS: raise HTTPException(415, "不支持的软件包格式")
    if body.size <= 0: raise HTTPException(400, "文件大小无效")
    if body.size > settings.SOFTWARE_MAX_SIZE_GB * 1024 * 1024 * 1024: raise HTTPException(413, "文件大小超过限制")

    # 本地存储后端没有 OSS 直传能力 — 回退到同步上传
    if storage_service.is_local:
        return ok({"mode": "sync"}, "使用同步上传")

    # 2. 生成 oss_key 与 presigned URL — 原始文件名直接在 OSS 中可辨识
    oss_key = oss_key_for_upload(body.filename, f"{settings.OSS_SOFTWARE_PREFIX}/{brand}")
    part_size = settings.UPLOAD_PART_SIZE_MB * 1024 * 1024
    expire = settings.UPLOAD_PRESIGN_EXPIRE_MINUTES

    payload = {
        "oss_key": oss_key,
        "filename": body.filename,
        "brand": brand,
        "category": category,
        "version": body.version,
        "description": body.description,
        "content_type": body.content_type,
        "size": body.size,
        "software_id": body.software_id,
        "exp": datetime.now(timezone.utc) + timedelta(hours=UPLOAD_TOKEN_EXPIRE_HOURS),
    }

    if body.size > part_size:
        # multipart
        upload_id = await run_in_threadpool(storage_service._impl.create_multipart_upload, oss_key, body.content_type)
        num_parts = math.ceil(body.size / part_size)
        part_urls = [
            await run_in_threadpool(storage_service._impl.presign_part_upload, oss_key, upload_id, i + 1, expire)
            for i in range(num_parts)
        ]
        payload["mode"] = "multipart"
        payload["upload_id"] = upload_id
        token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
        return ok({
            "mode": "multipart", "token": token, "oss_key": oss_key,
            "part_size": part_size, "part_urls": part_urls,
            "expires_in": expire * 60,
        }, "凭证已签发")

    # single PUT
    upload_url = await run_in_threadpool(storage_service._impl.presign_single_put, oss_key, body.content_type, expire)
    payload["mode"] = "single"
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return ok({
        "mode": "single", "token": token, "oss_key": oss_key,
        "upload_url": upload_url, "expires_in": expire * 60,
    }, "凭证已签发")


@router.post("/upload/complete")
async def upload_complete(body: UploadCompleteBody, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    claims = _decode_upload_token(body.token)
    mode = claims.get("mode")
    oss_key = claims["oss_key"]

    if mode == "multipart":
        upload_id = claims["upload_id"]
        if not body.parts:
            raise HTTPException(400, "缺少分片信息")
        parts = [{"PartNumber": p.part_number, "ETag": p.etag} for p in sorted(body.parts, key=lambda x: x.part_number)]
        try:
            await run_in_threadpool(storage_service._impl.complete_multipart_upload, oss_key, upload_id, parts)
        except Exception:
            await run_in_threadpool(storage_service._impl.abort_multipart_upload, oss_key, upload_id)
            raise HTTPException(500, "合并分片失败，已取消上传")
    elif mode == "single":
        exists = await run_in_threadpool(storage_service._impl.head_object, oss_key)
        if not exists:
            raise HTTPException(400, "文件未上传至 OSS")
    else:
        raise HTTPException(400, "无效的上传凭证")

    # 写入 DB — 失败时清理已上传的文件
    existing_id = claims.get("software_id")
    if existing_id:
        sw = db.query(Software).filter(Software.id == existing_id).first()
        if not sw:
            await run_in_threadpool(storage_service.delete_file, oss_key)
            raise HTTPException(400, "软件不存在")
        try:
            db.add(SoftwareVersion(software_id=sw.id, version=claims["version"],
                                   file_size=claims["size"], file_hash=body.file_hash, oss_key=oss_key))
            sw.latest_version = claims["version"]
            db.commit()
            db.refresh(sw)
        except Exception:
            db.rollback()
            await run_in_threadpool(storage_service.delete_file, oss_key)
            raise
        return ok(sw.to_dict(include_versions=True), "版本已添加")

    sw = Software(filename=oss_key.rsplit("/", 1)[-1], original_name=claims["filename"],
                  brand=claims["brand"], category=claims["category"],
                  latest_version=claims["version"], description=claims.get("description"))
    try:
        db.add(sw)
        db.flush()
        db.add(SoftwareVersion(software_id=sw.id, version=claims["version"],
                               file_size=claims["size"], file_hash=body.file_hash, oss_key=oss_key))
        db.commit()
        db.refresh(sw)
    except Exception:
        db.rollback()
        await run_in_threadpool(storage_service.delete_file, oss_key)
        raise

    return ok(sw.to_dict(include_versions=True), "上传成功")


@router.post("/upload/abort")
async def upload_abort(body: UploadAbortBody, admin: User = Depends(require_admin)):
    claims = _decode_upload_token(body.token)
    mode = claims.get("mode")
    oss_key = claims["oss_key"]
    if mode == "multipart":
        await run_in_threadpool(storage_service._impl.abort_multipart_upload, oss_key, claims["upload_id"])
    elif mode == "single":
        await run_in_threadpool(storage_service.delete_file, oss_key)
    return ok(message="已取消")


@router.get("/brands/list")
async def brands(db: Session = Depends(get_db)):
    return ok(_valid_values(db, "sw_brand"))


@router.get("/categories/list")
async def categories(db: Session = Depends(get_db)):
    return ok(_valid_values(db, "sw_category"))


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
    meta = await run_in_threadpool(storage_service.upload_file, file.file, file.filename, f"{settings.OSS_SOFTWARE_PREFIX}/{sw.brand}", file.content_type)
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


class UpdateSoftwareBody(BaseModel):
    original_name: str | None = None
    brand: str | None = None
    category: str | None = None
    description: str | None = None


@router.patch("/{software_id}")
async def update_software(software_id: int, body: UpdateSoftwareBody, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    sw = db.query(Software).filter(Software.id == software_id).first()
    if not sw: raise HTTPException(404, "软件不存在")
    if body.brand is not None:
        if body.brand not in _valid_values(db, "sw_brand"):
            raise HTTPException(400, "无效品牌")
        sw.brand = body.brand
    if body.category is not None:
        if body.category not in _valid_values(db, "sw_category"):
            raise HTTPException(400, "无效分类")
        sw.category = body.category
    if body.original_name is not None:
        if not body.original_name.strip():
            raise HTTPException(400, "软件名不能为空")
        sw.original_name = body.original_name.strip()
    if body.description is not None:
        sw.description = body.description
    db.commit(); db.refresh(sw)
    return ok(sw.to_dict(), "更新成功")


@router.patch("/publish/bulk")
async def bulk_publish_software(body: "BulkPublishSoftwareBody", db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    q = db.query(Software)
    if body.ids is not None:
        if not body.ids:
            raise HTTPException(400, "请选择要操作的软件")
        q = q.filter(Software.id.in_(body.ids))
    else:
        if body.brand:
            q = q.filter(Software.brand == body.brand)
        if body.category:
            q = q.filter(Software.category == body.category)
        if body.keyword:
            q = q.filter(Software.original_name.ilike(f"%{body.keyword}%"))
    # Only flip rows whose state differs from the target — keeps the operation
    # idempotent and the response count meaningful.
    rows = q.filter(Software.is_published == (not body.publish)).all()
    for sw in rows:
        sw.is_published = body.publish
    db.commit()
    return ok({"count": len(rows), "publish": body.publish}, "发布成功" if body.publish else "取消发布成功")


class BulkPublishSoftwareBody(BaseModel):
    ids: list[int] | None = None
    brand: str | None = None
    category: str | None = None
    keyword: str | None = None
    publish: bool = True


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
