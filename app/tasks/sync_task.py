"""Scheduled maintenance tasks."""
import logging
import time
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.login_session import LoginSession
from app.models.sync_log import SyncLog
from app.models.token_blacklist import TokenBlacklist
from app.services.rag_sync_service import scan_documents, sync_document

logger = logging.getLogger(__name__)

MAX_RETRIES = 2
RETRY_INTERVAL_SECONDS = 3


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _record_sync_log(db: Session, action: str, status: str, document_id: int | None = None, error_message: str | None = None):
    db.add(SyncLog(action=action, status=status, document_id=document_id, error_message=error_message))
    db.commit()


def run_sync_once(db: Session) -> dict:
    """Orchestrate OSS → RAG sync: scan, add/update/delete documents in Milvus.

    For each changed document, retry up to MAX_RETRIES times with RETRY_INTERVAL_SECONDS
    between attempts. Failures are recorded in sync_logs.
    """
    logger.info("Starting OSS → RAG sync cycle")
    _record_sync_log(db, "scan", "success")

    changes = scan_documents(db)
    logger.info("Sync scan found %d changes", len(changes))

    stats = {"added": 0, "updated": 0, "deleted": 0, "failed": 0}

    for change in changes:
        action = change["action"]
        doc = change["document"]

        if action == "delete":
            # Remove from Milvus if it was previously synced
            if doc is not None:
                try:
                    from app.services.milvus_service import milvus_service
                    milvus_service.delete_by_document(doc.original_name)
                    doc.sync_status = "deleted"
                    doc.sync_time = now()
                    _record_sync_log(db, "delete", "success", document_id=doc.id)
                    stats["deleted"] += 1
                except Exception as e:
                    _record_sync_log(db, "delete", "failed", document_id=doc.id, error_message=str(e))
                    stats["failed"] += 1
            continue

        if doc is None:
            continue

        doc_id = doc.id
        last_error = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                sync_document(db, doc)
                doc.sync_status = "synced"
                doc.sync_time = now()
                _record_sync_log(db, action, "success", document_id=doc_id)
                if action == "add":
                    stats["added"] += 1
                else:
                    stats["updated"] += 1
                last_error = None
                break
            except Exception as e:
                last_error = str(e)
                logger.warning(
                    "Sync attempt %d/%d failed for document %d (%s): %s",
                    attempt, MAX_RETRIES, doc_id, doc.original_name, last_error,
                )
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_INTERVAL_SECONDS)

        if last_error is not None:
            doc.sync_status = "failed"
            doc.sync_time = now()
            _record_sync_log(db, action, "failed", document_id=doc_id, error_message=last_error)
            stats["failed"] += 1

    logger.info("Sync cycle complete: %s", stats)
    return {"status": "completed", "stats": stats}


def cleanup_expired_tokens():
    db = SessionLocal()
    try:
        db.query(TokenBlacklist).filter(TokenBlacklist.expires_at < now()).delete()
        db.commit()
    finally:
        db.close()


def cleanup_sessions():
    db = SessionLocal()
    try:
        cutoff = now() - timedelta(minutes=5)
        db.query(LoginSession).filter(LoginSession.last_active_at < cutoff).update({"is_active": False})
        db.commit()
    finally:
        db.close()


def scheduled_sync():
    db = SessionLocal()
    try:
        run_sync_once(db)
    finally:
        db.close()


class SyncScheduler:
    def __init__(self):
        self.scheduler = BackgroundScheduler(timezone="UTC")

    def start(self):
        if self.scheduler.running:
            return
        self.scheduler.add_job(scheduled_sync, "interval", minutes=settings.RAG_SYNC_INTERVAL_MINUTES, id="oss_rag_sync", replace_existing=True)
        self.scheduler.add_job(cleanup_expired_tokens, "interval", hours=1, id="token_cleanup", replace_existing=True)
        self.scheduler.add_job(cleanup_sessions, "interval", minutes=1, id="session_cleanup", replace_existing=True)
        self.scheduler.start()

    def stop(self):
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
