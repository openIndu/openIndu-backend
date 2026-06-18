"""Online statistics and dashboard API."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, require_admin
from app.models.document import Document
from app.models.login_session import LoginSession
from app.models.software import Software
from app.models.user import User
from app.models.visit_event import VisitEvent
from app.services.geo_service import GEO_POINTS

router = APIRouter(prefix="/stats")


def ok(data=None, message="操作成功"):
    return {"code": 200, "message": message, "data": data or {}}


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


@router.get("/dashboard")
async def dashboard_stats(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    now = _now()
    thirty_days_ago = now - timedelta(days=30)
    online_cutoff = now - timedelta(minutes=5)

    total_users = db.query(func.count(User.id)).scalar() or 0
    total_docs = db.query(func.count(Document.id)).scalar() or 0
    total_software = db.query(func.count(Software.id)).scalar() or 0
    new_users_30d = db.query(func.count(User.id)).filter(User.created_at >= thirty_days_ago).scalar() or 0
    visitors_30d = db.query(func.count(func.distinct(VisitEvent.ip_address))).filter(VisitEvent.created_at >= thirty_days_ago).scalar() or 0
    online_count = db.query(func.count(func.distinct(LoginSession.user_id))).filter(LoginSession.is_active.is_(True)).scalar() or 0
    online_visitors = db.query(func.count(func.distinct(VisitEvent.ip_address))).filter(VisitEvent.created_at >= online_cutoff).scalar() or 0
    anonymous_online = max(online_visitors - online_count, 0)

    reg_rows = (
        db.query(func.date(User.created_at).label("day"), func.count(User.id).label("cnt"))
        .filter(User.created_at >= thirty_days_ago)
        .group_by(func.date(User.created_at))
        .order_by(func.date(User.created_at))
        .all()
    )
    daily_registrations = [{"date": str(r.day), "count": r.cnt} for r in reg_rows]

    visit_rows = (
        db.query(func.date(VisitEvent.created_at).label("day"), func.count(func.distinct(VisitEvent.ip_address)).label("cnt"))
        .filter(VisitEvent.created_at >= thirty_days_ago)
        .group_by(func.date(VisitEvent.created_at))
        .order_by(func.date(VisitEvent.created_at))
        .all()
    )
    daily_visitors = [{"date": str(r.day), "count": r.cnt} for r in visit_rows]

    login_rows = (
        db.query(func.date(LoginSession.last_active_at).label("day"), func.count(func.distinct(LoginSession.user_id)).label("cnt"))
        .filter(LoginSession.last_active_at >= thirty_days_ago)
        .group_by(func.date(LoginSession.last_active_at))
        .order_by(func.date(LoginSession.last_active_at))
        .all()
    )
    daily_logins = [{"date": str(r.day), "count": r.cnt} for r in login_rows]

    geo: dict[str, dict[str, int | float | str]] = {}
    visit_geo_rows = (
        db.query(
            VisitEvent.geo_location.label("name"),
            VisitEvent.country_code.label("country_code"),
            func.count(func.distinct(VisitEvent.ip_address)).label("visitors"),
            func.count(func.distinct(VisitEvent.user_id)).label("registrations"),
        )
        .filter(VisitEvent.created_at >= online_cutoff)
        .group_by(VisitEvent.geo_location, VisitEvent.country_code)
        .all()
    )
    for row in visit_geo_rows:
        name = row.name or "未知"
        point = GEO_POINTS.get(name, GEO_POINTS["未知"])
        geo[name] = {
            "name": name,
            "country_code": row.country_code or point["country_code"],
            "lat": point["lat"],
            "lng": point["lng"],
            "visitors": row.visitors or 0,
            "registrations": row.registrations or 0,
            "online": 0,
            "anonymous": 0,
        }

    active_sessions = db.query(LoginSession).filter(LoginSession.is_active.is_(True)).all()
    for session in active_sessions:
        name = session.geo_location or "未知"
        point = GEO_POINTS.get(name, GEO_POINTS["未知"])
        entry = geo.setdefault(name, {
            "name": name,
            "country_code": point["country_code"],
            "lat": point["lat"],
            "lng": point["lng"],
            "visitors": 0,
            "registrations": 0,
            "online": 0,
            "anonymous": 0,
        })
        entry["online"] = int(entry["online"]) + 1

    for entry in geo.values():
        entry["anonymous"] = max(int(entry["visitors"]) - int(entry["online"]), 0)

    geo_list = sorted(geo.values(), key=lambda x: -(int(x["visitors"]) + int(x["online"])))

    return ok({
        "total_users": total_users,
        "total_docs": total_docs,
        "total_software": total_software,
        "new_users_30d": new_users_30d,
        "visitors_30d": visitors_30d,
        "online_count": online_count,
        "online_visitors": online_visitors,
        "anonymous_online": anonymous_online,
        "daily_registrations": daily_registrations,
        "daily_visitors": daily_visitors,
        "daily_logins": daily_logins,
        "geo_distribution": geo_list,
    })


@router.get("/online")
async def online(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    sessions = db.query(LoginSession).filter(LoginSession.is_active.is_(True)).all()
    geo: dict[str, int] = {}
    for s in sessions:
        key = s.geo_location or "unknown"
        geo[key] = geo.get(key, 0) + 1
    geo_list = [{"name": k, "count": v} for k, v in geo.items()]
    return ok({"online_users": len({s.user_id for s in sessions}), "sessions": len(sessions), "geo_distribution": geo_list})


@router.get("/login-history")
async def login_history(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None),
    status: str | None = Query(None),  # 'online' | 'offline' | None
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    q = (
        db.query(LoginSession, User.phone)
        .join(User, LoginSession.user_id == User.id, isouter=True)
        .order_by(LoginSession.last_active_at.desc())
    )
    if keyword:
        q = q.filter(User.phone.ilike(f"%{keyword}%"))
    if status == "online":
        q = q.filter(LoginSession.is_active.is_(True))
    elif status == "offline":
        q = q.filter(LoginSession.is_active.is_(False))
    total = q.count()
    rows = q.offset((page - 1) * size).limit(size).all()
    items = [{
        "id": session.id,
        "username": phone or f"ID:{session.user_id}",
        "ip": session.ip_address,
        "location": session.geo_location or "未知",
        "login_time": session.last_active_at.isoformat() if session.last_active_at else None,
        "is_active": session.is_active,
    } for session, phone in rows]
    return ok({"items": items, "total": total, "page": page, "size": size})
