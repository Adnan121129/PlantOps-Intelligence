from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError

# Leading bytes of allowed binary types. Text types are checked for being valid UTF-8.
_SIGNATURES = {
    ".pdf": [b"%PDF-"],
    ".png": [b"\x89PNG\r\n\x1a\n"],
    ".jpg": [b"\xff\xd8\xff"],
    ".jpeg": [b"\xff\xd8\xff"],
    ".xlsx": [b"PK\x03\x04"],
}


def validate_attachment(upload) -> None:
    suffix = Path(upload.name).suffix.lower()
    if suffix not in settings.PLANTOPS_ALLOWED_ATTACHMENT_EXTENSIONS:
        allowed = ", ".join(sorted(settings.PLANTOPS_ALLOWED_ATTACHMENT_EXTENSIONS))
        raise ValidationError(f"File type '{suffix or 'none'}' is not allowed. Allowed: {allowed}.")
    if upload.size > settings.PLANTOPS_MAX_ATTACHMENT_BYTES:
        raise ValidationError(f"File exceeds the {settings.PLANTOPS_MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB limit.")
    head = upload.read(2048)
    upload.seek(0)
    if suffix in _SIGNATURES:
        if not any(head.startswith(sig) for sig in _SIGNATURES[suffix]):
            raise ValidationError("File content does not match its extension.")
    else:
        try:
            head.decode("utf-8")
        except UnicodeDecodeError as exc:
            # A multi-byte character may be split at the 2048-byte boundary; retry trimmed.
            try:
                head[:-4].decode("utf-8")
            except UnicodeDecodeError:
                raise ValidationError("Text attachments must be UTF-8 encoded.") from exc
