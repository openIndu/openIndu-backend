"""Synchronization task API."""
import logging

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.dependencies import get_db, require_admin, require_auth
from app.core.utils import ok
from app.models.document import Document
from app.models.sync_log import SyncLog
from app.models.user import User
from app.tasks.sync_task import run_sync_once

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sync")


class TriggerBody(BaseModel):
    mode: str = "incremental"


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
    # See documents.py sync endpoint: when RAG sync is off this backend must
    # not run BGE-M3 embedding, so the manual full-library trigger is rejected
    # too. Syncs are produced offline and the vectors pushed to Milvus.
    if not settings.RAG_SYNC_ENABLED:
        raise HTTPException(503, "本环境已关闭 RAG 同步（RAG_SYNC_ENABLED=false），请在离线环境同步后导入向量")
    background_tasks.add_task(_run_sync_background, body.mode)
    return ok({"mode": body.mode, "status": "queued"}, "同步已在后台启动")


@router.get("/status")
async def sync_status(db: Session = Depends(get_db), user: User = Depends(require_auth)):
    rows = db.query(Document.sync_status).all()
    stats: dict[str, int] = {}
    for (status,) in rows:
        key = status or "pending"
        stats[key] = stats.get(key, 0) + 1
    pending_count = stats.get("pending", 0) + stats.get("failed", 0)
    # Surface the flag so the admin UI can disable its sync buttons instead of
    # letting the click fail with a 503 — one fewer round-trip, clearer UX.
    return ok({"documents": stats, "pending_count": pending_count, "rag_sync_enabled": settings.RAG_SYNC_ENABLED})


@router.get("/logs")
async def sync_logs(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    q = (
        db.query(SyncLog, Document.original_name)
        .outerjoin(Document, SyncLog.document_id == Document.id)
        .order_by(SyncLog.sync_time.desc())
    )
    total = q.count()
    rows = q.offset((page - 1) * size).limit(size).all()
    items = []
    for log, document_name in rows:
        item = log.to_dict()
        item["document_name"] = document_name
        items.append(item)
    return ok({"items": items, "total": total, "page": page, "size": size})
