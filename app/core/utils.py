"""Shared utility helpers."""
import re
from datetime import datetime, timezone

# Characters allowed in OSS object names: letters/digits/CJK/dot/dash/underscore/space.
# Everything else (path separators, control chars, &, ?, #, …) is stripped so
# the resulting key is safe to embed in URLs without re-encoding traps.
_SAFE_NAME_RE = re.compile(r"[^\w.\- 一-鿿]")


def _sanitize_filename(name: str) -> str:
    """Strip dangerous characters and collapse whitespace.

    Empty result after sanitising (e.g. caller passed ``///``) returns
    ``"file"`` so the caller still has a non-empty key segment.
    """
    cleaned = _SAFE_NAME_RE.sub("", name).strip().strip(".")
    return cleaned or "file"


def oss_key_for_upload(original_name: str, prefix: str) -> str:
    """Build a human-readable OSS object key.

    Format: ``{prefix}/{sanitized_stem}_{utc-yyyymmdd-hhmmss}.{ext}`` — the
    timestamp suffix dedupes re-uploads of the same file name so two users
    cannot silently overwrite each other.
    """
    if "." in original_name:
        stem, ext = original_name.rsplit(".", 1)
        ext = ext.lower()
    else:
        stem, ext = original_name, "bin"
    safe_stem = _sanitize_filename(stem)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    filename = f"{safe_stem}_{ts}.{ext}"
    return f"{prefix.strip('/')}/{filename}"


def mask_phone(phone: str | None) -> str | None:
    """Mask a phone number for privacy-preserving display.

    A standard Chinese mobile number (11 digits) becomes ``138****0000`` —
    the first 3 and last 4 digits are kept, the middle is masked. Empty values
    (``None`` / ``""``) are returned unchanged so callers can fall back to a
    non-phone placeholder (e.g. ``ID:5``) without it being masked.
    """
    if not phone:
        return phone
    s = phone.strip()
    if len(s) >= 7:
        return f"{s[:3]}****{s[-4:]}"
    return s


def ok(data=None, message: str = "操作成功"):
    """Standard success envelope shared by all API routers.

    Use an explicit ``None`` check, not ``data or {}`` — an empty list (e.g. a
    brand+category combo with no series) is falsy and would be coerced to ``{}``,
    breaking array consumers on the frontend (``.filter is not a function``).
    """
    return {"code": 200, "message": message, "data": data if data is not None else {}}
