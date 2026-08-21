from __future__ import annotations

import os


def is_allowed(chat_id, allowlist):
    """True only if allowlist is non-empty AND chat_id is in it.

    An empty allowlist means 'setup mode': nothing is accepted yet.
    """
    return bool(allowlist) and chat_id in allowlist


MIME_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/heic": ".heic",
    "image/heif": ".heif",
}


def _ext_from_document(doc):
    name = doc.get("file_name") or ""
    _, ext = os.path.splitext(name)
    if ext:
        return ext.lower()
    mime = (doc.get("mime_type") or "").lower()
    return MIME_EXT.get(mime, ".bin")


def extract_image(message):
    """Return (file_id, ext) for the best image in a message, or None.

    - 'photo': list of PhotoSize; pick the largest by width*height (ext '.jpg').
    - 'document' with image/* mime: use it (ext from file_name or mime).
    Anything else returns None.
    """
    if not isinstance(message, dict):
        return None
    photos = message.get("photo")
    if photos:
        best = max(photos, key=lambda p: p.get("width", 0) * p.get("height", 0))
        return (best["file_id"], ".jpg")
    doc = message.get("document")
    if doc:
        mime = (doc.get("mime_type") or "").lower()
        if mime.startswith("image/"):
            return (doc["file_id"], _ext_from_document(doc))
    return None


def build_filename(dt, ext, existing):
    """Build 'YYYYMMDD_HHMMSS<ext>', adding _NN to avoid names in 'existing'."""
    if not ext.startswith("."):
        ext = "." + ext
    base = dt.strftime("%Y%m%d_%H%M%S")
    candidate = base + ext
    if candidate not in existing:
        return candidate
    n = 1
    while True:
        candidate = "%s_%02d%s" % (base, n, ext)
        if candidate not in existing:
            return candidate
        n += 1


def default_save_dir():
    return os.path.join(
        os.environ.get("USERPROFILE", os.path.expanduser("~")),
        "Pictures",
        "iPhoneScreenshots",
    )


def expand_save_dir(raw):
    """Expand %VARS% and ~ in a configured path; fall back to default."""
    if not raw:
        return default_save_dir()
    return os.path.expanduser(os.path.expandvars(raw))
