from __future__ import annotations

import contextlib
import contextvars
from typing import Iterable

from .models import Notification

_muted: contextvars.ContextVar[bool] = contextvars.ContextVar("notifications_muted", default=False)


@contextlib.contextmanager
def muted():
    """Used by bulk loaders so replayed history does not flood users' notification centres."""
    token = _muted.set(True)
    try:
        yield
    finally:
        _muted.reset(token)


def notify(recipients: Iterable, title: str, message: str = "", link: str = "") -> None:
    if _muted.get():
        return
    rows = [Notification(recipient=u, title=title[:200], message=message, link=link[:200])
            for u in {u.pk: u for u in recipients if u is not None and u.is_active}.values()]
    Notification.objects.bulk_create(rows)


def notify_role(role: str, title: str, message: str = "", link: str = "", *, exclude=None) -> None:
    from apps.accounts.models import User

    qs = User.objects.filter(role=role, is_active=True)
    if exclude is not None:
        qs = qs.exclude(pk=exclude.pk)
    notify(qs, title, message, link)
