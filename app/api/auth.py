"""Authentication API."""
from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from app.core.dependencies import get_db, require_auth
from app.models.user import User
from app.services.auth_service import auth_service

router = APIRouter(prefix="/auth")
limiter = Limiter(key_func=get_remote_address)
security = HTTPBearer()


class PhoneRequest(BaseModel):
    phone: str


class AuthRequest(BaseModel):
    phone: str
    code: str


class RefreshRequest(BaseModel):
    refresh_token: str


class ProfileUpdateRequest(BaseModel):
    nickname: str | None = None


def ok(data=None, message: str = "操作成功"):
    return {"code": 200, "message": message, "data": data or {}}


@router.post("/send-code")
@limiter.limit("5/minute")
async def send_code(request: Request, body: PhoneRequest, db: Session = Depends(get_db)):
    auth_service.send_code(db, body.phone)
    return ok(message="验证码已发送")


@router.post("/login")
@limiter.limit("10/minute")
async def login(request: Request, body: AuthRequest, db: Session = Depends(get_db)):
    return ok(auth_service.login(db, body.phone, body.code), "登录成功")


@router.post("/register")
async def register(body: AuthRequest, db: Session = Depends(get_db)):
    return ok(auth_service.register(db, body.phone, body.code), "注册成功")


@router.post("/refresh")
async def refresh(body: RefreshRequest, db: Session = Depends(get_db)):
    return ok(auth_service.refresh_token(db, body.refresh_token), "刷新成功")


@router.get("/me")
async def me(current_user: User = Depends(require_auth)):
    return ok(current_user.to_dict())


@router.patch("/me")
async def update_me(body: ProfileUpdateRequest, db: Session = Depends(get_db), current_user: User = Depends(require_auth)):
    nickname = (body.nickname or "").strip()
    current_user.nickname = nickname or None
    db.commit()
    db.refresh(current_user)
    return ok(current_user.to_dict(), "资料已更新")


@router.post("/logout")
async def logout(credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db), current_user: User = Depends(require_auth)):
    auth_service.logout(db, credentials.credentials)
    return ok(message="已登出")
