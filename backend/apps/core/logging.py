import logging
import re

_SENSITIVE = re.compile(r"(password|passwd|secret|token|authorization|sessionid|csrftoken)=([^\s&;]+)", re.I)


class RedactSensitiveFilter(logging.Filter):
    """Masks credential-like key=value pairs before log records are emitted."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - never break logging
            return True
        redacted = _SENSITIVE.sub(lambda m: f"{m.group(1)}=***", message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True
