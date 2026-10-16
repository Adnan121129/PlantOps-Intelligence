from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError

from apps.core.settings_registry import get_setting

MAX_SINGLE_EXPENSE = Decimal("100000000.00")


def validate_expense_amount(amount: Decimal) -> None:
    if amount is None:
        raise ValidationError({"amount": "Amount is required."})
    if amount <= 0:
        raise ValidationError({"amount": "Amount must be greater than zero."})
    if amount.as_tuple().exponent < -2:
        raise ValidationError({"amount": "At most 2 decimal places are allowed."})
    if amount > MAX_SINGLE_EXPENSE:
        raise ValidationError({"amount": "Amount exceeds the maximum allowed for a single record."})


def validate_currency(currency: str) -> None:
    base = get_setting("base_currency")
    if currency != base:
        raise ValidationError({"currency": f"Only the base currency ({base}) is supported; convert before recording."})


def maintenance_department():
    from apps.core.models import Department

    code = get_setting("maintenance_department_code")
    return Department.objects.filter(code=code).first() if code else None
