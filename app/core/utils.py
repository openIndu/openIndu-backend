"""Shared utility helpers."""


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
