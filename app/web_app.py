"""FastAPI Web REST application on port 8004."""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from starlette.responses import JSONResponse

from app.api import auth, brand_mapping, config, documents, files, portal, software, stats, sync, users
from app.core.database import engine
from app.middleware.online_stats import OnlineStatsMiddleware
from app.middleware.token_blacklist import TokenBlacklistMiddleware
from app.models import Base
from app.models.admin_audit_log import AdminAuditLog  # noqa: F401
from app.models.document import Document  # noqa: F401
from app.models.download_log import DownloadLog  # noqa: F401
from app.models.login_session import LoginSession  # noqa: F401
from app.models.portal_content import PortalContent  # noqa: F401
from app.models.sms_code import SmsCode  # noqa: F401
from app.models.software import Software, SoftwareVersion  # noqa: F401
from app.models.sync_log import SyncLog  # noqa: F401
from app.models.system_config import SystemConfig  # noqa: F401
from app.models.token_blacklist import TokenBlacklist  # noqa: F401
from app.models.user import User  # noqa: F401
from app.tasks.sync_task import SyncScheduler

limiter = Limiter(key_func=get_remote_address, default_limits=["50/second"])
scheduler = SyncScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    scheduler.start()
    yield
    scheduler.stop()


app = FastAPI(title="openIndu Backend Web API", version="0.1.0", lifespan=lifespan)
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(status_code=429, content={"code": 429, "detail": "请求过于频繁"})


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"code": 500, "detail": "服务器内部错误"})


app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://openindu.com", "https://admin.openindu.com", "http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(TokenBlacklistMiddleware)
app.add_middleware(OnlineStatsMiddleware)

for router in [auth.router, portal.router, users.router, stats.router, documents.router, software.router, sync.router, config.router, brand_mapping.router, files.router]:
    app.include_router(router, prefix="/api/v1")


@app.get("/api/v1/health")
async def health():
    return {"code": 200, "message": "ok", "data": {"service": "openIndu-backend-web"}}
