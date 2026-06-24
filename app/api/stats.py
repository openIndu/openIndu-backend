"""Online statistics and dashboard API."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, require_admin
from app.core.utils import mask_phone, ok
from app.models.document import Document
from app.models.login_session import LoginSession
from app.models.software import Software
from app.models.user import User
from app.models.visit_event import VisitEvent
from app.services.geo_service import GEO_POINTS

router = APIRouter(prefix="/stats")

CST = timezone(timedelta(hours=8))  # Asia/Shanghai


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _to_naive_utc(dt: datetime) -> datetime:
    """Convert a timezone-aware datetime to naive UTC for DB comparison."""
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _today_range_utc() -> tuple[datetime, datetime]:
    """Return [today 00:00 CST, tomorrow 00:00 CST) as naive UTC."""
    now_cst = datetime.now(CST)
    start_cst = now_cst.replace(hour=0, minute=0, second=0, microsecond=0)
    end_cst = start_cst + timedelta(days=1)
    return (_to_naive_utc(start_cst), _to_naive_utc(end_cst))


def _month_range_utc() -> tuple[datetime, datetime]:
    """Return [1st of this month 00:00 CST, 1st of next month 00:00 CST) as naive UTC."""
    now_cst = datetime.now(CST)
    start_cst = now_cst.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start_cst.month == 12:
        end_cst = start_cst.replace(year=start_cst.year + 1, month=1)
    else:
        end_cst = start_cst.replace(month=start_cst.month + 1)
    return (_to_naive_utc(start_cst), _to_naive_utc(end_cst))


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

    # ---- period stats: today / this month (Asia/Shanghai) ----
    today_start, today_end = _today_range_utc()
    month_start, month_end = _month_range_utc()

    # Geo distribution — based on this-month visit_events, split cleanly by
    # whether the visit was authenticated. Anonymous and authenticated buckets
    # are counted independently against ip_address (anon) / user_id (auth) so
    # the two columns are honest and never need subtraction guards.
    geo: dict[str, dict[str, int | float | str]] = {}
    anon_geo_rows = (
        db.query(
            VisitEvent.geo_location.label("name"),
            VisitEvent.country_code.label("country_code"),
            func.count(func.distinct(VisitEvent.ip_address)).label("anonymous"),
        )
        .filter(
            VisitEvent.user_id.is_(None),
            VisitEvent.created_at >= month_start,
            VisitEvent.created_at < month_end,
        )
        .group_by(VisitEvent.geo_location, VisitEvent.country_code)
        .all()
    )
    for row in anon_geo_rows:
        name = row.name or "未知"
        point = GEO_POINTS.get(name, GEO_POINTS["未知"])
        geo[name] = {
            "name": name,
            "country_code": row.country_code or point["country_code"],
            "lat": point["lat"],
            "lng": point["lng"],
            "visitors": int(row.anonymous or 0),  # legacy field — total dot weight; populated by both buckets below
            "registrations": 0,
            "online": 0,
            "anonymous": int(row.anonymous or 0),
        }

    auth_geo_rows = (
        db.query(
            VisitEvent.geo_location.label("name"),
            VisitEvent.country_code.label("country_code"),
            func.count(func.distinct(VisitEvent.user_id)).label("authenticated"),
        )
        .filter(
            VisitEvent.user_id.isnot(None),
            VisitEvent.created_at >= month_start,
            VisitEvent.created_at < month_end,
        )
        .group_by(VisitEvent.geo_location, VisitEvent.country_code)
        .all()
    )
    for row in auth_geo_rows:
        name = row.name or "未知"
        point = GEO_POINTS.get(name, GEO_POINTS["未知"])
        auth_n = int(row.authenticated or 0)
        entry = geo.setdefault(name, {
            "name": name,
            "country_code": row.country_code or point["country_code"],
            "lat": point["lat"],
            "lng": point["lng"],
            "visitors": 0,
            "registrations": 0,
            "online": 0,
            "anonymous": 0,
        })
        entry["online"] = int(entry["online"]) + auth_n  # "online" is the legacy field name the map renders for the auth bucket
        entry["registrations"] = int(entry["registrations"]) + auth_n
        entry["visitors"] = int(entry["visitors"]) + auth_n

    geo_list = sorted(geo.values(), key=lambda x: -(int(x["anonymous"]) + int(x["online"])))

    current_active_users = db.query(func.count(func.distinct(LoginSession.user_id))).filter(
        LoginSession.is_active.is_(True)
    ).scalar() or 0

    today_active_users = db.query(func.count(func.distinct(VisitEvent.ip_address))).filter(
        VisitEvent.created_at >= today_start,
        VisitEvent.created_at < today_end,
    ).scalar() or 0

    today_new_users = db.query(func.count(User.id)).filter(
        User.created_at >= today_start,
        User.created_at < today_end,
    ).scalar() or 0

    today_new_docs = db.query(func.count(Document.id)).filter(
        Document.upload_time >= today_start,
        Document.upload_time < today_end,
    ).scalar() or 0

    today_new_software = db.query(func.count(Software.id)).filter(
        Software.created_at >= today_start,
        Software.created_at < today_end,
    ).scalar() or 0

    month_active_users = db.query(func.count(func.distinct(VisitEvent.ip_address))).filter(
        VisitEvent.created_at >= month_start,
        VisitEvent.created_at < month_end,
    ).scalar() or 0

    # Cumulative across all time — answers "how many distinct visitors have ever
    # reached the site?" Anonymous + authenticated together, deduped by IP.
    total_visitors = db.query(func.count(func.distinct(VisitEvent.ip_address))).scalar() or 0

    month_new_users = db.query(func.count(User.id)).filter(
        User.created_at >= month_start,
        User.created_at < month_end,
    ).scalar() or 0

    month_new_docs = db.query(func.count(Document.id)).filter(
        Document.upload_time >= month_start,
        Document.upload_time < month_end,
    ).scalar() or 0

    month_new_software = db.query(func.count(Software.id)).filter(
        Software.created_at >= month_start,
        Software.created_at < month_end,
    ).scalar() or 0

    # ---- monthly trends (1st to today, zero-filled) ----
    today_cst = datetime.now(CST).date()
    month_start_cst_date = today_cst.replace(day=1)
    month_days = (today_cst - month_start_cst_date).days + 1

    monthly_registrations: list[dict[str, int | str]] = []
    monthly_visitors: list[dict[str, int | str]] = []
    monthly_anon_visitors: list[dict[str, int | str]] = []
    for i in range(month_days):
        day_date = month_start_cst_date + timedelta(days=i)
        date_str = str(day_date)
        monthly_registrations.append({"date": date_str, "count": 0})
        monthly_visitors.append({"date": date_str, "count": 0})
        monthly_anon_visitors.append({"date": date_str, "count": 0})

    reg_month_rows = (
        db.query(func.date(User.created_at).label("day"), func.count(User.id).label("cnt"))
        .filter(User.created_at >= month_start, User.created_at < month_end)
        .group_by(func.date(User.created_at))
        .order_by(func.date(User.created_at))
        .all()
    )
    reg_map = {str(r.day): r.cnt for r in reg_month_rows}
    for item in monthly_registrations:
        item["count"] = reg_map.get(item["date"], 0)

    # All visits (anon + authenticated), deduped by IP per day — this replaces
    # the previous "logged-in only" series, which was always near zero because
    # the bulk of traffic is anonymous.
    visit_month_rows = (
        db.query(
            func.date(VisitEvent.created_at).label("day"),
            func.count(func.distinct(VisitEvent.ip_address)).label("cnt"),
        )
        .filter(
            VisitEvent.created_at >= month_start,
            VisitEvent.created_at < month_end,
        )
        .group_by(func.date(VisitEvent.created_at))
        .order_by(func.date(VisitEvent.created_at))
        .all()
    )
    visit_map = {str(r.day): r.cnt for r in visit_month_rows}
    for item in monthly_visitors:
        item["count"] = visit_map.get(item["date"], 0)

    # Anonymous-only series (user_id IS NULL).
    anon_month_rows = (
        db.query(
            func.date(VisitEvent.created_at).label("day"),
            func.count(func.distinct(VisitEvent.ip_address)).label("cnt"),
        )
        .filter(
            VisitEvent.user_id.is_(None),
            VisitEvent.created_at >= month_start,
            VisitEvent.created_at < month_end,
        )
        .group_by(func.date(VisitEvent.created_at))
        .order_by(func.date(VisitEvent.created_at))
        .all()
    )
    anon_map = {str(r.day): r.cnt for r in anon_month_rows}
    for item in monthly_anon_visitors:
        item["count"] = anon_map.get(item["date"], 0)

    # Logged-in series (user_id IS NOT NULL), deduped by user_id per day.
    monthly_login_visitors = [{"date": str(month_start_cst_date + timedelta(days=i)), "count": 0} for i in range(month_days)]
    login_month_rows = (
        db.query(
            func.date(VisitEvent.created_at).label("day"),
            func.count(func.distinct(VisitEvent.user_id)).label("cnt"),
        )
        .filter(
            VisitEvent.user_id.isnot(None),
            VisitEvent.created_at >= month_start,
            VisitEvent.created_at < month_end,
        )
        .group_by(func.date(VisitEvent.created_at))
        .order_by(func.date(VisitEvent.created_at))
        .all()
    )
    login_map = {str(r.day): r.cnt for r in login_month_rows}
    for item in monthly_login_visitors:
        item["count"] = login_map.get(item["date"], 0)

    # ---- yearly anonymous visit trend (last 12 months, by month) ----
    # 365 daily points are too dense to render readably, so we aggregate by
    # month. Window: from the 1st of "11 months ago" through today, inclusive.
    months: list[tuple[int, int]] = []
    y, m = today_cst.year, today_cst.month
    for _ in range(12):
        months.append((y, m))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    months.reverse()

    year_start_cst = datetime(months[0][0], months[0][1], 1, tzinfo=CST)
    year_start_utc = _to_naive_utc(year_start_cst)

    yearly_anon_rows = (
        db.query(
            func.to_char(VisitEvent.created_at, "YYYY-MM").label("ym"),
            func.count(func.distinct(VisitEvent.ip_address)).label("cnt"),
        )
        .filter(
            VisitEvent.user_id.is_(None),
            VisitEvent.created_at >= year_start_utc,
        )
        .group_by("ym")
        .all()
    )
    yearly_map = {r.ym: r.cnt for r in yearly_anon_rows}
    yearly_anon_visitors = [
        {"date": f"{yy:04d}-{mm:02d}", "count": yearly_map.get(f"{yy:04d}-{mm:02d}", 0)}
        for yy, mm in months
    ]

    # Last 12 months, all visits (anon + authenticated), deduped by ip_address.
    yearly_all_rows = (
        db.query(
            func.to_char(VisitEvent.created_at, "YYYY-MM").label("ym"),
            func.count(func.distinct(VisitEvent.ip_address)).label("cnt"),
        )
        .filter(VisitEvent.created_at >= year_start_utc)
        .group_by("ym")
        .all()
    )
    yearly_all_map = {r.ym: r.cnt for r in yearly_all_rows}
    yearly_visitors = [
        {"date": f"{yy:04d}-{mm:02d}", "count": yearly_all_map.get(f"{yy:04d}-{mm:02d}", 0)}
        for yy, mm in months
    ]

    return ok({
        "total_users": total_users,
        "total_docs": total_docs,
        "total_software": total_software,
        "total_visitors": total_visitors,
        "new_users_30d": new_users_30d,
        "visitors_30d": visitors_30d,
        "online_count": online_count,
        "online_visitors": online_visitors,
        "anonymous_online": anonymous_online,
        "daily_registrations": daily_registrations,
        "daily_visitors": daily_visitors,
        "daily_logins": daily_logins,
        "geo_distribution": geo_list,
        # period stats
        "current_active_users": current_active_users,
        "today_active_users": today_active_users,
        "today_new_users": today_new_users,
        "today_new_docs": today_new_docs,
        "today_new_software": today_new_software,
        "month_active_users": month_active_users,
        "month_new_users": month_new_users,
        "month_new_docs": month_new_docs,
        "month_new_software": month_new_software,
        "monthly_registrations": monthly_registrations,
        "monthly_visitors": monthly_visitors,
        "monthly_anon_visitors": monthly_anon_visitors,
        "monthly_login_visitors": monthly_login_visitors,
        "yearly_anon_visitors": yearly_anon_visitors,
        "yearly_visitors": yearly_visitors,
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
        "username": mask_phone(phone) or f"ID:{session.user_id}",
        "ip": session.ip_address,
        "location": session.geo_location or "未知",
        "login_time": session.last_active_at.isoformat() if session.last_active_at else None,
        "is_active": session.is_active,
    } for session, phone in rows]
    return ok({"items": items, "total": total, "page": page, "size": size})
