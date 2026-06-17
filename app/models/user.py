"""User model."""
from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, String, func

from app.models import Base


class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    phone = Column(String(20), unique=True, nullable=False, index=True)
    role = Column(String(20), nullable=False, default="user")
    is_active = Column(Boolean, nullable=False, default=True)
    is_blacklisted = Column(Boolean, nullable=False, default=False)
    blacklisted_at = Column(DateTime, nullable=True)
    blacklisted_by = Column(BigInteger, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    last_login = Column(DateTime, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "phone": self.phone,
            "role": self.role,
            "is_active": self.is_active,
            "is_blacklisted": self.is_blacklisted,
            "blacklisted_at": self.blacklisted_at.isoformat() if self.blacklisted_at else None,
            "blacklisted_by": self.blacklisted_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_login": self.last_login.isoformat() if self.last_login else None,
        }
