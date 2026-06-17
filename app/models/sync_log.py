"""OSS to RAG synchronization log model."""
from sqlalchemy import BigInteger, Column, DateTime, String, Text, func

from app.models import Base


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
            "sync_time": self.sync_time.isoformat() if self.sync_time else None,
        }
