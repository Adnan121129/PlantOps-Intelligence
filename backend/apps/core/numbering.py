from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from .models import NumberSequence


def next_number(prefix: str, *, width: int = 5, year: int | None = None) -> str:
    """Returns e.g. 'WO-2026-00042'. Locks the sequence row so concurrent requests never collide."""
    year = year or timezone.now().year
    key = f"{prefix}-{year}"
    with transaction.atomic():
        NumberSequence.objects.get_or_create(key=key)
        seq = NumberSequence.objects.select_for_update().get(key=key)
        seq.last_value += 1
        seq.save(update_fields=["last_value"])
        return f"{key}-{seq.last_value:0{width}d}"
