"""Clock for *recorded* timestamps (submitted_at, decided_at, audit timestamps, ...).

In normal operation it is simply `timezone.now()`. The demo seeder replays months of
history and sets a simulated time so that workflow timestamps are realistic. Validation
rules ("cannot be in the future") always compare against the real `timezone.now()`.
"""
from __future__ import annotations

import contextlib
import contextvars
import datetime as dt

from django.utils import timezone

_override: contextvars.ContextVar[dt.datetime | None] = contextvars.ContextVar("plantops_clock", default=None)


def now() -> dt.datetime:
    return _override.get() or timezone.now()


@contextlib.contextmanager
def at(moment: dt.datetime):
    token = _override.set(moment)
    try:
        yield
    finally:
        _override.reset(token)


def set_now(moment: dt.datetime | None) -> None:
    _override.set(moment)
