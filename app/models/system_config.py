"""System business configuration model."""
from sqlalchemy import BigInteger, Column, DateTime, String, Text, func

from app.models import Base


class SystemConfig(Base):
    __tablename__ = "system_configs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    config_key = Column(String(100), unique=True, nullable=False, index=True)
    config_value = Column(Text, nullable=False, default="")
    description = Column(String(255), nullable=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    def to_dict(self) -> dict:
        return {
            "key": self.config_key,
            "value": self.config_value,
            "description": self.description,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
