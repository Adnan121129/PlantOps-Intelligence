from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.accounts import audit
from apps.accounts.models import AuditLog
from apps.core import clock
from apps.core.settings_registry import get_setting

from .models import OvertimeRecord


@transaction.atomic
def decide_overtime(record: OvertimeRecord, *, user, approve: bool, comment: str = "") -> OvertimeRecord:
    """Approving fixes the cost (hours x rate x multiplier) and posts it to the cost ledger."""
    from apps.costs.models import CostCategory, OperationalExpense

    record = OvertimeRecord.objects.select_for_update().select_related("employee").get(pk=record.pk)
    if record.status != OvertimeRecord.Status.PENDING:
        raise ValidationError("This overtime record has already been decided.")
    if record.recorded_by_id == user.pk:
        raise ValidationError("Overtime must be approved by someone other than the person who recorded it.")
    if not approve and not comment.strip():
        raise ValidationError({"comment": "A reason is required when rejecting overtime."})
    record.status = OvertimeRecord.Status.APPROVED if approve else OvertimeRecord.Status.REJECTED
    record.decided_by, record.decided_at = user, clock.now()
    if approve and record.employee.hourly_rate is not None:
        record.cost = (record.hours * record.employee.hourly_rate * record.rate_multiplier).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP)
    record.save()
    if approve and record.cost:
        OperationalExpense.objects.create(
            expense_date=record.date, category=CostCategory.LABOR, cost_type=OperationalExpense.CostType.ACTUAL,
            amount=record.cost, currency=get_setting("base_currency"),
            description=f"Overtime {record.hours}h {record.employee.employee_code}: {record.reason}"[:255],
            department=record.employee.department, work_order=record.work_order,
            asset=record.work_order.asset if record.work_order else None,
            plant_unit=record.work_order.asset.plant_unit if record.work_order else None,
            source=OperationalExpense.Source.OVERTIME, overtime=record, recorded_by=user,
        )
    audit.record(user, AuditLog.Action.APPROVE if approve else AuditLog.Action.REJECT, record,
                 entity_repr=f"Overtime {record.employee.employee_code} {record.date}", message=comment)
    return record
