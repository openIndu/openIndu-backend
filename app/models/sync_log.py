"""OSS to RAG synchronization log model."""
from datetime import timedelta, timezone

from sqlalchemy import BigInteger, Column, DateTime, String, Text, func

from app.models import Base

TZ_SHANGHAI = timezone(timedelta(hours=8))


def _to_shanghai_iso(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TZ_SHANGHAI).isoformat()


class SyncLog(Base):
    __tablename__ = "sync_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    document_id = Column(BigInteger, nullable=True, index=True)
    action = Column(String(20), nullable=True)
    status = Column(String(20), nullable=False, index=True)
    error_message = Column(Text, nullable=True)
    sync_time = Column(DateTime, server_default=func.now(), nullable=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "document_id": self.document_id,
            "action": self.action,
            "status": self.status,
            "error_message": self.error_message,
            "sync_time": _to_shanghai_iso(self.sync_time),
        }
