"""FastAPI MCP application on port 8005."""
from fastapi import FastAPI, Header, HTTPException

from app.core.config import settings
from app.mcp.server import mcp

app = FastAPI(title="openIndu Backend MCP API", version="0.1.0")


@app.middleware("http")
async def api_key_auth(request, call_next):
    if request.url.path not in ("/health", "/api/v1/health"):
        api_key = request.headers.get("x-api-key")
        if settings.MCP_API_KEY and api_key != settings.MCP_API_KEY:
            raise HTTPException(status_code=401, detail="Invalid MCP API key")
    return await call_next(request)


@app.get("/health")
async def health():
    return {"code": 200, "message": "ok", "data": {"service": "openIndu-backend-mcp"}}

# FastMCP can be mounted by runners that support ASGI/SSE transports. Keep the
# protocol object importable at app.mcp.server:mcp for Claude Code MCP configs.
