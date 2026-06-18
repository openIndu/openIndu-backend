"""Visit tracking API for dashboard analytics."""
from fastapi import APIRouter, Depends, Request
from jose import JWTError
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.models.visit_event import VisitEvent
from app.services.auth_service import decode_token
from app.services.geo_service import resolve_ip_geo

router = APIRouter(prefix="/visits")


def ok(data=None, message="操作成功"):
    return {"code": 200, "message": message, "data": data or {}}


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    return forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "unknown")


class VisitBody(BaseModel):
    path: str = "/"


@router.post("/track")
async def track_visit(body: VisitBody, request: Request, db: Session = Depends(get_db)):
    ip = client_ip(request)
    ua = request.headers.get("user-agent", "")[:512]
    geo = resolve_ip_geo(ip)
    user_id = None
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        try:
            payload = decode_token(auth.split(" ", 1)[1])
            if payload.get("type") == "access" and payload.get("sub"):
                user_id = int(payload["sub"])
        except (JWTError, ValueError):
            user_id = None
    event = VisitEvent(
        ip_address=ip,
        user_agent=ua,
        path=body.path[:512] or "/",
        geo_location=str(geo["name"]),
        country_code=str(geo["country_code"]),
        is_authenticated=user_id is not None,
        user_id=user_id,
    )
    db.add(event)
    db.commit()
    return ok({"tracked": True})
