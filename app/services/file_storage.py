"""Local filesystem storage service for documents and software packages.

Replaces MinIO/OSS for business file storage (MinIO is kept only for Milvus internals).
"""

import hashlib
import uuid
from pathlib import Path
from typing import BinaryIO

from app.core.config import settings

# Streaming chunk — keeps memory flat for large software packages.
_CHUNK = 8 * 1024 * 1024  # 8 MiB


class FileStorageService:
    """Store and retrieve files on the local filesystem under DATA_DIR."""

    def __init__(self) -> None:
        self._root = Path(settings.DATA_DIR)

    # -- helpers -----------------------------------------------------------

    def _ensure_dir(self, *parts: str) -> Path:
        d = self._root.joinpath(*parts)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _oss_key_to_path(self, oss_key: str) -> Path:
        return self._root / oss_key

    # -- public API --------------------------------------------------------

    def upload_file(
        self,
        file_stream: BinaryIO,
        original_name: str,
        prefix: str,
        content_type: str | None = None,
    ) -> dict:
        ext = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else "bin"
        filename = f"{uuid.uuid4().hex}.{ext}"
        oss_key = f"{prefix.strip('/')}/{filename}"

        target = self._ensure_dir(prefix.strip("/"))
        # Stream to disk in chunks, hashing as we go — no full-file memory copy.
        h = hashlib.sha256()
        size = 0
        file_stream.seek(0)
        with open(target / filename, "wb") as f:
            while True:
                chunk = file_stream.read(_CHUNK)
                if not chunk:
                    break
                f.write(chunk)
                h.update(chunk)
                size += len(chunk)

        return {
            "oss_key": oss_key,
            "filename": filename,
            "file_hash": h.hexdigest(),
            "file_size": size,
        }

    def delete_file(self, oss_key: str) -> None:
        path = self._oss_key_to_path(oss_key)
        if path.exists():
            path.unlink()

    def get_file_path(self, oss_key: str) -> Path:
        path = self._oss_key_to_path(oss_key)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {oss_key}")
        return path

    def list_objects(self, prefix: str) -> list[dict]:
        objects: list[dict] = []
        target_dir = self._root / prefix.strip("/")
        if target_dir.exists():
            for f in target_dir.rglob("*"):
                if f.is_file():
                    st = f.stat()
                    objects.append({
                        "key": str(f.relative_to(self._root)),
                        "size": st.st_size,
                        "last_modified": st.st_mtime,
                    })
        return objects


file_storage = FileStorageService()
