"""Software package and version models."""
from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import relationship

from app.models import Base


class Software(Base):
    __tablename__ = "software"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    filename = Column(String(500), nullable=False)
    original_name = Column(String(500), nullable=False)
    brand = Column(String(50), nullable=False, index=True)
    category = Column(String(50), nullable=False, index=True)
    latest_version = Column(String(100), nullable=True)
    download_count = Column(Integer, nullable=False, default=0)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    versions = relationship("SoftwareVersion", back_populates="software", cascade="all, delete-orphan")

    def to_dict(self, include_versions: bool = False) -> dict:
        data = {
            "id": self.id,
            "filename": self.filename,
            "original_name": self.original_name,
            "brand": self.brand,
            "category": self.category,
            "latest_version": self.latest_version,
            "download_count": self.download_count,
            "description": self.description,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        if include_versions:
            data["versions"] = [v.to_dict() for v in self.versions]
        return data


class SoftwareVersion(Base):
    __tablename__ = "software_versions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    software_id = Column(BigInteger, ForeignKey("software.id"), nullable=False, index=True)
    version = Column(String(100), nullable=False)
    file_size = Column(BigInteger, nullable=True)
    file_hash = Column(String(64), nullable=True, index=True)
    oss_key = Column(String(500), nullable=False, unique=True)
    download_count = Column(Integer, nullable=False, default=0)
    upload_time = Column(DateTime, server_default=func.now(), nullable=False)
    is_active = Column(Boolean, nullable=False, default=True)

    software = relationship("Software", back_populates="versions")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "software_id": self.software_id,
            "version": self.version,
            "file_size": self.file_size,
            "file_hash": self.file_hash,
            "oss_key": self.oss_key,
            "download_count": self.download_count,
            "upload_time": self.upload_time.isoformat() if self.upload_time else None,
            "is_active": self.is_active,
        }
