"""Online statistics API."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, require_admin
from app.models.login_session import LoginSession
from app.models.user import User

router = APIRouter(prefix="/stats")


def ok(data=None, message="操作成功"):
    return {"code": 200, "message": message, "data": data or {}}


@router.get("/online")
async def online(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    sessions = db.query(LoginSession).filter(LoginSession.is_active.is_(True)).all()
    geo = {}
    for s in sessions:
        key = s.geo_location or "unknown"
        geo[key] = geo.get(key, 0) + 1
    return ok({"online_users": len({s.user_id for s in sessions}), "sessions": len(sessions), "geo_distribution": geo})


@router.get("/login-history")
async def login_history(page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100), db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    q = db.query(LoginSession).order_by(LoginSession.last_active_at.desc())
    total = q.count()
    items = [{"user_id": s.user_id, "ip_address": s.ip_address, "user_agent": s.user_agent, "geo_location": s.geo_location, "last_active_at": s.last_active_at.isoformat() if s.last_active_at else None, "is_active": s.is_active} for s in q.offset((page - 1) * size).limit(size).all()]
    return ok({"items": items, "total": total, "page": page, "size": size})
