"""Reporting-period helpers.

A reporting period is an inclusive range of *local business dates* in a plant's
time zone. It is converted to a half-open UTC interval [start, end) for queries so
that every timestamp belongs to exactly one day.
"""
from __future__ import annotations

import datetime as dt
import zoneinfo
from dataclasses import dataclass
from decimal import Decimal

from django.utils import timezone


@dataclass(frozen=True)
class Period:
    date_from: dt.date
    date_to: dt.date
    tz: zoneinfo.ZoneInfo

    @property
    def start(self) -> dt.datetime:
        return dt.datetime.combine(self.date_from, dt.time.min, tzinfo=self.tz)

    @property
    def end(self) -> dt.datetime:
        return dt.datetime.combine(self.date_to + dt.timedelta(days=1), dt.time.min, tzinfo=self.tz)

    @property
    def effective_end(self) -> dt.datetime:
        """Period end clipped to 'now' so ongoing periods are not over-counted."""
        return min(self.end, timezone.now())

    @property
    def days(self) -> int:
        return (self.date_to - self.date_from).days + 1

    @property
    def elapsed_hours(self) -> Decimal:
        seconds = max((self.effective_end - self.start).total_seconds(), 0)
        return Decimal(seconds) / Decimal(3600)

    def as_dict(self) -> dict:
        return {
            "date_from": self.date_from.isoformat(),
            "date_to": self.date_to.isoformat(),
            "timezone": str(self.tz),
            "days": self.days,
        }


def local_today(tz: zoneinfo.ZoneInfo) -> dt.date:
    return timezone.now().astimezone(tz).date()


def overlap_hours(start: dt.datetime, end: dt.datetime | None, window_start: dt.datetime, window_end: dt.datetime) -> Decimal:
    """Hours of [start, end) that fall inside [window_start, window_end). Open events run until window_end."""
    effective_end = window_end if end is None else min(end, window_end)
    effective_start = max(start, window_start)
    seconds = (effective_end - effective_start).total_seconds()
    return Decimal(max(seconds, 0)) / Decimal(3600)
