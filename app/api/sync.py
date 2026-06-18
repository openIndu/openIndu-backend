"""Synchronization task API."""
import logging

from fastapi import APIRouter, BackgroundTasks, Body, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, require_admin, require_auth
from app.core.database import SessionLocal
from app.models.document import Document
from app.models.sync_log import SyncLog
from app.models.user import User
from app.tasks.sync_task import run_sync_once

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sync")


class TriggerBody(BaseModel):
    mode: str = "incremental"


def ok(data=None, message="操作成功"):
    return {"code": 200, "message": message, "data": data or {}}


def _run_sync_background(mode: str):
    db = SessionLocal()
    try:
        run_sync_once(db)
    except Exception as exc:
        logger.error("Background sync failed (mode=%s): %s", mode, exc)
    finally:
        db.close()


@router.post("/trigger")
async def trigger_sync(
    background_tasks: BackgroundTasks,
    body: TriggerBody = Body(default=TriggerBody()),
    admin: User = Depends(require_admin),
):
    background_tasks.add_task(_run_sync_background, body.mode)
    return ok({"mode": body.mode, "status": "queued"}, "同步已在后台启动")


@router.get("/status")
async def sync_status(db: Session = Depends(get_db), user: User = Depends(require_auth)):
    rows = db.query(Document.sync_status).all()
    stats: dict[str, int] = {}
    for (status,) in rows:
        key = status or "pending"
        stats[key] = stats.get(key, 0) + 1
    pending_count = stats.get("pending", 0)
    return ok({"documents": stats, "pending_count": pending_count, "status": "running" if pending_count else "idle"})


@router.get("/logs")
async def sync_logs(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    q = db.query(SyncLog).order_by(SyncLog.sync_time.desc())
    total = q.count()
    items = [x.to_dict() for x in q.offset((page - 1) * size).limit(size).all()]
    return ok({"items": items, "total": total, "page": page, "size": size})
