"""Known system settings with defaults and validation.

Administrators change these through the API (`/api/core/settings/`). Code reads them via
`get_setting(key)`, which falls back to the default when no row exists.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from django.core.exceptions import ValidationError


@dataclass(frozen=True)
class SettingSpec:
    key: str
    default: Any
    description: str
    validate: Callable[[Any], None]


def _int_range(lo: int, hi: int) -> Callable[[Any], None]:
    def check(value: Any) -> None:
        if not isinstance(value, int) or isinstance(value, bool) or not lo <= value <= hi:
            raise ValidationError(f"Must be an integer between {lo} and {hi}.")

    return check


def _currency(value: Any) -> None:
    if not isinstance(value, str) or len(value) != 3 or not value.isalpha() or not value.isupper():
        raise ValidationError("Must be a 3-letter ISO 4217 currency code, e.g. USD.")


def _any_str(value: Any) -> None:
    if not isinstance(value, str) or len(value) > 20:
        raise ValidationError("Must be a string of at most 20 characters.")


SPECS: dict[str, SettingSpec] = {
    spec.key: spec
    for spec in [
        SettingSpec(
            "pm_compliance_grace_days",
            0,
            "Days after the due date that a preventive task may be completed and still count as compliant.",
            _int_range(0, 30),
        ),
        SettingSpec(
            "base_currency",
            "USD",
            "Currency used for all monetary records and analytics. Multi-currency conversion is not supported.",
            _currency,
        ),
        SettingSpec(
            "fiscal_year_start_month",
            1,
            "First calendar month (1-12) of the fiscal year, used for year-to-date budget figures.",
            _int_range(1, 12),
        ),
        SettingSpec(
            "default_plant_code",
            "",
            "Plant whose time zone defines reporting periods when no plant filter is selected.",
            _any_str,
        ),
        SettingSpec(
            "slow_moving_days",
            90,
            "An item with stock on hand and no issue for this many days is classified as slow-moving.",
            _int_range(7, 730),
        ),
        SettingSpec(
            "repeat_failure_window_days",
            30,
            "A failure on the same asset within this many days of the previous failure counts as a repeat failure.",
            _int_range(1, 365),
        ),
        SettingSpec(
            "maintenance_department_code",
            "MNT",
            "Department to which work-order costs (labour, parts, contractors) are attributed in cost analytics.",
            _any_str,
        ),
        SettingSpec(
            "report_entry_deadline_hours",
            4,
            "Hours after the end of a shift by which the operational report is expected to be submitted.",
            _int_range(0, 72),
        ),
    ]
}


def get_setting(key: str) -> Any:
    from .models import SystemSetting

    spec = SPECS[key]
    row = SystemSetting.objects.filter(key=key).only("value").first()
    return spec.default if row is None else row.value


def validate_setting(key: str, value: Any) -> None:
    if key not in SPECS:
        raise ValidationError(f"Unknown setting '{key}'.")
    SPECS[key].validate(value)
