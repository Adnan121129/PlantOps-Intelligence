"""Request context: client IP for audit records, and the plant time zone for local dates.

Activating the default plant's time zone makes `timezone.localdate()` and date filters
resolve to the plant's business date rather than the server's UTC date.
"""
from __future__ import annotations

import contextvars
import time
import zoneinfo

from django.utils import timezone

_client_ip: contextvars.ContextVar[str | None] = contextvars.ContextVar("client_ip", default=None)
_tz_cache: dict = {"tz": None, "at": 0.0}
TZ_CACHE_SECONDS = 60


def current_ip() -> str | None:
    return _client_ip.get()


def default_plant_timezone() -> zoneinfo.ZoneInfo:
    if _tz_cache["tz"] is None or time.monotonic() - _tz_cache["at"] > TZ_CACHE_SECONDS:
        from apps.core.period import plant_tz, resolve_plant

        try:
            _tz_cache["tz"] = plant_tz(resolve_plant(None))
        except Exception:  # database not ready (e.g. during migrations)
            return zoneinfo.ZoneInfo("UTC")
        _tz_cache["at"] = time.monotonic()
    return _tz_cache["tz"]


def reset_timezone_cache() -> None:
    _tz_cache["tz"] = None


class RequestContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # REMOTE_ADDR only: X-Forwarded-For is client-controlled unless a trusted proxy rewrites it.
        token = _client_ip.set(request.META.get("REMOTE_ADDR"))
        timezone.activate(default_plant_timezone())
        try:
            return self.get_response(request)
        finally:
            timezone.deactivate()
            _client_ip.reset(token)
