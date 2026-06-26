"""Online statistics and dashboard API."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, require_admin
from app.core.utils import iso_utc, mask_phone, ok
from app.models.document import Document
from app.models.login_session import LoginSession
from app.models.software import Software
from app.models.user import User
from app.models.visit_event import VisitEvent
from app.services.geo_service import lookup_point

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


def _visitor_key():
    """Browser visitor key for UV: visitor_id first, historical rows by IP."""
    return func.coalesce(VisitEvent.visitor_id, func.concat("ip:", VisitEvent.ip_address))


def _quality_visit_query(db: Session):
    """Default dashboard visit scope: real page views, excluding local/unknown."""
    return db.query(VisitEvent).filter(
        VisitEvent.event_type == "page_view",
        VisitEvent.geo_location.is_distinct_from("本地开发"),
        VisitEvent.geo_location.is_distinct_from("未知"),
    )


def _pv_count(db: Session, start: datetime | None = None, end: datetime | None = None) -> int:
    q = _quality_visit_query(db)
    if start is not None:
        q = q.filter(VisitEvent.created_at >= start)
    if end is not None:
        q = q.filter(VisitEvent.created_at < end)
    return q.with_entities(func.count(VisitEvent.id)).scalar() or 0


def _uv_count(db: Session, start: datetime | None = None, end: datetime | None = None) -> int:
    q = _quality_visit_query(db)
    if start is not None:
        q = q.filter(VisitEvent.created_at >= start)
    if end is not None:
        q = q.filter(VisitEvent.created_at < end)
    return q.with_entities(func.count(func.distinct(_visitor_key()))).scalar() or 0


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
    online_clients = db.query(func.count(func.distinct(LoginSession.client_id))).filter(LoginSession.is_active.is_(True), LoginSession.client_id.isnot(None)).scalar() or 0
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

    total_pv = _pv_count(db)
    total_uv = _uv_count(db)
    today_pv = _pv_count(db, today_start, today_end)
    today_uv = _uv_count(db, today_start, today_end)
    month_pv = _pv_count(db, month_start, month_end)
    month_uv = _uv_count(db, month_start, month_end)
    current_5m_pv = _pv_count(db, online_cutoff)
    current_5m_uv = _uv_count(db, online_cutoff)

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
        point = lookup_point(name, row.country_code)
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
        point = lookup_point(name, row.country_code)
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

    # Backward-compatible visitor fields now map to UV (visitor_id-first,
    # historical IP fallback) and use the same dashboard quality filters.
    current_total_visitors = current_5m_uv

    today_active_users = today_uv

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

    month_active_users = month_uv

    # Cumulative across all time — UV (visitor_id first, historical IP fallback).
    total_visitors = total_uv

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
    monthly_pv: list[dict[str, int | str]] = []
    monthly_uv: list[dict[str, int | str]] = []
    monthly_anon_visitors: list[dict[str, int | str]] = []
    for i in range(month_days):
        day_date = month_start_cst_date + timedelta(days=i)
        date_str = str(day_date)
        monthly_registrations.append({"date": date_str, "count": 0})
        monthly_visitors.append({"date": date_str, "count": 0})
        monthly_pv.append({"date": date_str, "count": 0})
        monthly_uv.append({"date": date_str, "count": 0})
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

    # All page views (PV) per day.
    pv_month_rows = (
        db.query(
            func.date(VisitEvent.created_at).label("day"),
            func.count(VisitEvent.id).label("cnt"),
        )
        .filter(
            VisitEvent.event_type == "page_view",
            VisitEvent.geo_location.is_distinct_from("本地开发"),
            VisitEvent.geo_location.is_distinct_from("未知"),
            VisitEvent.created_at >= month_start,
            VisitEvent.created_at < month_end,
        )
        .group_by(func.date(VisitEvent.created_at))
        .order_by(func.date(VisitEvent.created_at))
        .all()
    )
    pv_map = {str(r.day): r.cnt for r in pv_month_rows}
    for item in monthly_pv:
        item["count"] = pv_map.get(item["date"], 0)

    # Unique visitors (UV) per day — visitor_id first, historical IP fallback.
    uv_month_rows = (
        db.query(
            func.date(VisitEvent.created_at).label("day"),
            func.count(func.distinct(_visitor_key())).label("cnt"),
        )
        .filter(
            VisitEvent.event_type == "page_view",
            VisitEvent.geo_location.is_distinct_from("本地开发"),
            VisitEvent.geo_location.is_distinct_from("未知"),
            VisitEvent.created_at >= month_start,
            VisitEvent.created_at < month_end,
        )
        .group_by(func.date(VisitEvent.created_at))
        .order_by(func.date(VisitEvent.created_at))
        .all()
    )
    visit_map = {str(r.day): r.cnt for r in uv_month_rows}
    for item in monthly_uv:
        item["count"] = visit_map.get(item["date"], 0)
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

    # Last 12 months, all page views (PV).
    yearly_pv_rows = (
        db.query(
            func.to_char(VisitEvent.created_at, "YYYY-MM").label("ym"),
            func.count(VisitEvent.id).label("cnt"),
        )
        .filter(
            VisitEvent.event_type == "page_view",
            VisitEvent.geo_location.is_distinct_from("本地开发"),
            VisitEvent.geo_location.is_distinct_from("未知"),
            VisitEvent.created_at >= year_start_utc,
        )
        .group_by("ym")
        .all()
    )
    yearly_pv_map = {r.ym: r.cnt for r in yearly_pv_rows}
    yearly_pv = [
        {"date": f"{yy:04d}-{mm:02d}", "count": yearly_pv_map.get(f"{yy:04d}-{mm:02d}", 0)}
        for yy, mm in months
    ]

    # Last 12 months, unique visitors (UV), visitor_id first with IP fallback.
    yearly_uv_rows = (
        db.query(
            func.to_char(VisitEvent.created_at, "YYYY-MM").label("ym"),
            func.count(func.distinct(_visitor_key())).label("cnt"),
        )
        .filter(
            VisitEvent.event_type == "page_view",
            VisitEvent.geo_location.is_distinct_from("本地开发"),
            VisitEvent.geo_location.is_distinct_from("未知"),
            VisitEvent.created_at >= year_start_utc,
        )
        .group_by("ym")
        .all()
    )
    yearly_all_map = {r.ym: r.cnt for r in yearly_uv_rows}
    yearly_uv = [
        {"date": f"{yy:04d}-{mm:02d}", "count": yearly_all_map.get(f"{yy:04d}-{mm:02d}", 0)}
        for yy, mm in months
    ]
    yearly_visitors = yearly_uv

    return ok({
        "total_users": total_users,
        "total_docs": total_docs,
        "total_software": total_software,
        "total_visitors": total_visitors,
        "total_pv": total_pv,
        "total_uv": total_uv,
        "new_users_30d": new_users_30d,
        "visitors_30d": visitors_30d,
        "online_count": online_count,
        "online_clients": online_clients,
        "online_visitors": online_visitors,
        "anonymous_online": anonymous_online,
        "daily_registrations": daily_registrations,
        "daily_visitors": daily_visitors,
        "daily_logins": daily_logins,
        "geo_distribution": geo_list,
        # period stats
        "current_active_users": current_active_users,
        "current_total_visitors": current_total_visitors,
        "current_5m_pv": current_5m_pv,
        "current_5m_uv": current_5m_uv,
        "today_active_users": today_active_users,
        "today_pv": today_pv,
        "today_uv": today_uv,
        "today_new_users": today_new_users,
        "today_new_docs": today_new_docs,
        "today_new_software": today_new_software,
        "month_active_users": month_active_users,
        "month_pv": month_pv,
        "month_uv": month_uv,
        "month_new_users": month_new_users,
        "month_new_docs": month_new_docs,
        "month_new_software": month_new_software,
        "monthly_registrations": monthly_registrations,
        "monthly_visitors": monthly_visitors,
        "monthly_pv": monthly_pv,
        "monthly_uv": monthly_uv,
        "monthly_anon_visitors": monthly_anon_visitors,
        "monthly_login_visitors": monthly_login_visitors,
        "yearly_anon_visitors": yearly_anon_visitors,
        "yearly_visitors": yearly_visitors,
        "yearly_pv": yearly_pv,
        "yearly_uv": yearly_uv,
    })


@router.get("/online")
async def online(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    sessions = db.query(LoginSession).filter(LoginSession.is_active.is_(True)).all()
    geo: dict[str, int] = {}
    for s in sessions:
        key = s.geo_location or "unknown"
        geo[key] = geo.get(key, 0) + 1
    geo_list = [{"name": k, "count": v} for k, v in geo.items()]
    return ok({
        "online_users": len({s.user_id for s in sessions}),
        "online_clients": len({s.client_id for s in sessions if getattr(s, "client_id", None)}),
        "sessions": len(sessions),
        "geo_distribution": geo_list,
    })


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
        # stored as naive UTC; iso_utc adds the +00:00 marker
        "login_time": iso_utc(session.last_active_at),
        "is_active": session.is_active,
    } for session, phone in rows]
    return ok({"items": items, "total": total, "page": page, "size": size})


@router.get("/visit-logs")
async def visit_logs(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    keyword: str | None = Query(None),       # matches masked phone's source or IP
    authed: str | None = Query(None),         # 'yes' (登录) | 'no' (匿名) | None
    include_local: bool = Query(False),       # 本地开发 / 内网访问默认隐藏
    include_unknown: bool = Query(False),     # geo='未知' (无法解析) 默认隐藏
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Visit log (anonymous + authenticated), newest first.

    Backed by visit_events. "本地开发" (private/loopback) and "未知" (unresolvable)
    visits are hidden unless include_local / include_unknown is true — matches
    the dashboard map's filter so both views agree on what counts as a visit.
    Search matches phone or IP; authed filters logged-in vs anon.
    """
    q = (
        db.query(VisitEvent, User.phone)
        .join(User, VisitEvent.user_id == User.id, isouter=True)
        .order_by(VisitEvent.created_at.desc())
    )
    if not include_local:
        q = q.filter(VisitEvent.geo_location.is_distinct_from("本地开发"))
    if not include_unknown:
        q = q.filter(VisitEvent.geo_location.is_distinct_from("未知"))
    if keyword:
        like = f"%{keyword.strip()}%"
        q = q.filter(or_(User.phone.ilike(like), VisitEvent.ip_address.ilike(like)))
    if authed == "yes":
        q = q.filter(VisitEvent.is_authenticated.is_(True))
    elif authed == "no":
        q = q.filter(VisitEvent.is_authenticated.is_(False))

    total = q.count()
    rows = q.offset((page - 1) * size).limit(size).all()
    items = [{
        "id": ev.id,
        "username": mask_phone(phone) if phone else None,
        "ip": ev.ip_address,
        "location": ev.geo_location or "未知",
        "path": ev.path,
        "is_authenticated": ev.is_authenticated,
        # stored as naive UTC; iso_utc adds the +00:00 marker
        "time": iso_utc(ev.created_at),
    } for ev, phone in rows]
    return ok({"items": items, "total": total, "page": page, "size": size})
