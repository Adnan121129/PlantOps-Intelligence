"""Parse reporting-period and plant filters from API requests."""
from __future__ import annotations

import datetime as dt
import zoneinfo

from django.core.exceptions import ValidationError

from .models import Plant, PlantUnit
from .settings_registry import get_setting
from .timeutils import Period, local_today

MAX_PERIOD_DAYS = 3 * 366


def resolve_plant(plant_id: str | int | None) -> Plant | None:
    if plant_id not in (None, ""):
        try:
            return Plant.objects.get(pk=int(plant_id))
        except (Plant.DoesNotExist, ValueError, TypeError) as exc:
            raise ValidationError({"plant": "Unknown plant."}) from exc
    code = get_setting("default_plant_code")
    plant = Plant.objects.filter(code=code).first() if code else None
    return plant or Plant.objects.filter(is_active=True).order_by("id").first()


def plant_tz(plant: Plant | None) -> zoneinfo.ZoneInfo:
    return zoneinfo.ZoneInfo(plant.timezone if plant else "UTC")


def _parse_date(value: str, field: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError({field: "Use the YYYY-MM-DD format."}) from exc


def period_from_params(params, *, default_days: int = 30) -> tuple[Period, Plant | None, PlantUnit | None]:
    """Returns (period, plant, unit). Defaults to the last `default_days` local days including today."""
    unit = None
    unit_id = params.get("unit")
    if unit_id not in (None, ""):
        try:
            unit = PlantUnit.objects.select_related("plant").get(pk=int(unit_id))
        except (PlantUnit.DoesNotExist, ValueError, TypeError) as exc:
            raise ValidationError({"unit": "Unknown plant unit."}) from exc
    plant = unit.plant if unit else resolve_plant(params.get("plant"))
    tz = plant_tz(plant)
    today = local_today(tz)
    date_to = _parse_date(params["date_to"], "date_to") if params.get("date_to") else today
    date_from = (
        _parse_date(params["date_from"], "date_from")
        if params.get("date_from")
        else date_to - dt.timedelta(days=default_days - 1)
    )
    if date_from > date_to:
        raise ValidationError({"date_from": "The start date must be on or before the end date."})
    if (date_to - date_from).days + 1 > MAX_PERIOD_DAYS:
        raise ValidationError({"date_from": f"Reporting periods are limited to {MAX_PERIOD_DAYS} days."})
    return Period(date_from, date_to, tz), plant, unit
