"""File download endpoint — serves files from local storage (only when STORAGE_BACKEND=local)."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.core.dependencies import require_auth
from app.models.user import User
from app.services.storage_service import storage_service

router = APIRouter(prefix="/files")


@router.get("/{oss_key:path}")
async def download_file(oss_key: str, user: User = Depends(require_auth)):
    """Stream a file from local storage. Auth + daily-limit are already enforced
    at the download-link generation step in documents/software APIs."""
    if not storage_service.is_local:
        raise HTTPException(status_code=404, detail="此端点仅在本地存储模式下可用")
    try:
        path = storage_service.get_file_path(oss_key)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(str(path))
