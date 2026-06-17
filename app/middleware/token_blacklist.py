"""Middleware that rejects revoked JWTs."""
from fastapi import Request
from jose import JWTError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.core.database import SessionLocal
from app.models.token_blacklist import TokenBlacklist
from app.services.auth_service import decode_token


class TokenBlacklistMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth.split(" ", 1)[1]
            try:
                payload = decode_token(token)
                jti = payload.get("jti")
                if jti:
                    db = SessionLocal()
                    try:
                        if db.query(TokenBlacklist).filter(TokenBlacklist.jti == jti).first():
                            return JSONResponse(status_code=401, content={"code": 401, "detail": "Token 已被撤销"})
                    finally:
                        db.close()
            except JWTError:
                pass
        return await call_next(request)
