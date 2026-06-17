"""Unified storage facade — delegates to local filesystem or S3 based on STORAGE_BACKEND.

Usage:
    from app.services.storage_service import storage_service
    meta = storage_service.upload_file(content, name, prefix)
    url  = storage_service.get_download_url(oss_key)
"""

from app.core.config import settings
from app.services.file_storage import FileStorageService, file_storage
from app.services.oss_service import OSSService, oss_service


class StorageService:
    """Facade that routes to the active backend."""

    def __init__(self) -> None:
        self._backend = settings.STORAGE_BACKEND

    @property
    def _impl(self):
        return file_storage if self._backend == "local" else oss_service

    @property
    def is_local(self) -> bool:
        return self._backend == "local"

    # -- delegated methods -------------------------------------------------

    def upload_file(self, file_content: bytes, original_name: str, prefix: str,
                    content_type: str | None = None) -> dict:
        return self._impl.upload_file(file_content, original_name, prefix, content_type)

    def delete_file(self, oss_key: str) -> None:
        self._impl.delete_file(oss_key)

    def list_objects(self, prefix: str) -> list[dict]:
        return self._impl.list_objects(prefix)

    # -- download URL ------------------------------------------------------

    def get_download_url(self, oss_key: str) -> dict:
        """Return a dict with 'url' and 'expires_in' suitable for the API response."""
        if self._backend == "local":
            return {
                "url": f"/api/v1/files/{oss_key.lstrip('/')}",
                "expires_in": None,  # local URLs don't expire
            }
        # S3 / OSS mode: generate presigned URL
        url = self._impl.generate_presigned_url(
            oss_key, settings.PRESIGNED_URL_EXPIRE_MINUTES
        )
        return {
            "url": url,
            "expires_in": settings.PRESIGNED_URL_EXPIRE_MINUTES * 60,
        }

    def get_file_path(self, oss_key: str):
        """Only valid in local mode — returns the filesystem path."""
        if not self.is_local:
            raise RuntimeError("get_file_path is only available in local storage mode")
        return self._impl.get_file_path(oss_key)


storage_service = StorageService()
