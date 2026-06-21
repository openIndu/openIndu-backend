"""Document metadata model."""
from datetime import timezone, timedelta

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, String, Text, func

from app.models import Base

# Shanghai timezone (UTC+8)
TZ_SHANGHAI = timezone(timedelta(hours=8))


def _to_shanghai_iso(dt):
    """Convert a UTC-naive datetime to Shanghai timezone ISO string."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TZ_SHANGHAI).isoformat()


class Document(Base):
    __tablename__ = "documents"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    filename = Column(String(500), nullable=False)
    original_name = Column(String(500), nullable=False)
    brand = Column(String(50), nullable=False, index=True)
    category = Column(String(50), nullable=False, index=True)
    file_size = Column(BigInteger, nullable=True)
    file_hash = Column(String(64), nullable=True, index=True)
    oss_key = Column(String(500), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    download_count = Column(Integer, nullable=False, default=0)
    sync_status = Column(String(20), nullable=False, default="pending")
    is_published = Column(Boolean, nullable=False, default=False)
    upload_time = Column(DateTime, server_default=func.now(), nullable=False)
    sync_time = Column(DateTime, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "filename": self.filename,
            "original_name": self.original_name,
            "brand": self.brand,
            "category": self.category,
            "file_size": self.file_size,
            "file_hash": self.file_hash,
            "oss_key": self.oss_key,
            "description": self.description,
            "download_count": self.download_count,
            "sync_status": self.sync_status,
            "is_published": self.is_published,
            "upload_time": _to_shanghai_iso(self.upload_time),
            "sync_time": _to_shanghai_iso(self.sync_time),
        }
