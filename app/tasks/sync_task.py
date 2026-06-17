"""Scheduled maintenance tasks."""
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.login_session import LoginSession
from app.models.sync_log import SyncLog
from app.models.token_blacklist import TokenBlacklist


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def run_sync_once(db: Session) -> dict:
    """Placeholder for OSS -> RAG sync orchestration."""
    db.add(SyncLog(action="scan", status="success", error_message=None))
    db.commit()
    return {"status": "started", "message": "OSS→RAG 同步占位任务已记录"}


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
