"""Synchronization task API."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, require_admin, require_auth
from app.models.document import Document
from app.models.sync_log import SyncLog
from app.models.user import User
from app.tasks.sync_task import run_sync_once

router = APIRouter(prefix="/sync")


def ok(data=None, message="操作成功"):
    return {"code": 200, "message": message, "data": data or {}}


@router.post("/trigger")
async def trigger_sync(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    result = run_sync_once(db)
    return ok(result, "同步已触发")


@router.get("/status")
async def sync_status(db: Session = Depends(get_db), user: User = Depends(require_auth)):
    rows = db.query(Document.sync_status).all()
    stats = {}
    for (status,) in rows:
        stats[status] = stats.get(status, 0) + 1
    return ok({"documents": stats})


@router.get("/logs")
async def sync_logs(page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    q = db.query(SyncLog).order_by(SyncLog.sync_time.desc())
    total = q.count()
    items = [x.to_dict() for x in q.offset((page - 1) * size).limit(size).all()]
    return ok({"items": items, "total": total, "page": page, "size": size})
