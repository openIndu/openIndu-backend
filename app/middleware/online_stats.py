"""Middleware that updates login session activity."""
from datetime import datetime, timezone

from fastapi import Request
from jose import JWTError
from sqlalchemy.exc import IntegrityError
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.database import SessionLocal
from app.models.login_session import LoginSession
from app.services.auth_service import decode_token
from app.services.geo_service import resolve_ip_geo


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _client_ip(request: Request) -> str:
    from app.core.utils import real_client_ip
    return real_client_ip(request) or "unknown"


class OnlineStatsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            try:
                payload = decode_token(auth.split(" ", 1)[1])
                if payload.get("type") == "access" and payload.get("sub"):
                    db = SessionLocal()
                    try:
                        user_id = int(payload["sub"])
                        ip = _client_ip(request)
                        ua = request.headers.get("user-agent", "")[:512]
                        geo = resolve_ip_geo(ip)
                        session = db.query(LoginSession).filter(
                            LoginSession.user_id == user_id,
                            LoginSession.ip_address == ip,
                            LoginSession.user_agent == ua,
                        ).first()
                        if session:
                            session.last_active_at = _now()
                            session.is_active = True
                            session.geo_location = str(geo["name"])
                        else:
                            db.add(LoginSession(
                                user_id=user_id,
                                ip_address=ip,
                                user_agent=ua,
                                geo_location=str(geo["name"]),
                                last_active_at=_now(),
                                is_active=True,
                            ))
                        db.commit()
                    except IntegrityError:
                        db.rollback()
                    finally:
                        db.close()
            except (JWTError, ValueError):
                pass
        return await call_next(request)
