"""ResourceTag model — stores dynamic brand / category metadata."""
from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, String, func

from app.models import Base


class ResourceTag(Base):
    __tablename__ = "resource_tags"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    type = Column(String(20), nullable=False, index=True)   # brand | doc_category | sw_category
    value = Column(String(100), nullable=False)              # slug used in DB (e.g. siemens)
    label_zh = Column(String(200), nullable=False)           # Chinese display name
    is_active = Column(Boolean, nullable=False, default=True)
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "value": self.value,
            "label_zh": self.label_zh,
            "is_active": self.is_active,
            "sort_order": self.sort_order,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
