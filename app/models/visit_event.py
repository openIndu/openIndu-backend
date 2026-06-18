"""Anonymous/authenticated visit event model for dashboard analytics."""
from sqlalchemy import BigInteger, Boolean, Column, DateTime, String, func

from app.models import Base


class VisitEvent(Base):
    __tablename__ = "visit_events"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    ip_address = Column(String(64), nullable=False, index=True)
    user_agent = Column(String(512), nullable=False, default="")
    path = Column(String(512), nullable=False, default="/")
    geo_location = Column(String(255), nullable=True)
    country_code = Column(String(32), nullable=True)
    is_authenticated = Column(Boolean, nullable=False, default=False, index=True)
    user_id = Column(BigInteger, nullable=True, index=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False, index=True)
