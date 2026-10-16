"""Work-order lifecycle, downtime recording and preventive-maintenance generation.

Lifecycle:  REPORTED -> ASSIGNED -> IN_PROGRESS -> AWAITING_VERIFICATION -> COMPLETED
            (any open state) -> CANCELLED (reason required)
            AWAITING_VERIFICATION -> IN_PROGRESS when the verifier returns the work.
'Overdue' and 'blocked' are indicators, not lifecycle states.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.accounts import audit
from apps.accounts.models import AuditLog
from apps.assets.models import EquipmentAsset
from apps.core import clock
from apps.core.numbering import next_number
from apps.core.period import plant_tz
from apps.core.settings_registry import get_setting

from .models import DowntimeEvent, MaintenanceSchedule, WorkOrder

S = WorkOrder.Status
CLOCK_SKEW = dt.timedelta(minutes=5)


def _now() -> dt.datetime:
    return clock.now()


def _minute(value: dt.datetime) -> dt.datetime:
    return value.replace(second=0, microsecond=0)


def _not_future(value: dt.datetime | None, field: str) -> None:
    if value is not None and value > timezone.now() + CLOCK_SKEW:
        raise ValidationError({field: "This time cannot be in the future."})


def _transition(wo: WorkOrder, allowed: tuple, target: str, user, **extra) -> None:
    if wo.status not in allowed:
        raise ValidationError(f"A work order that is '{wo.get_status_display()}' cannot move to "
                              f"'{S(target).label}'.")
    before = wo.status
    wo.status = target
    wo.save()
    audit.record(user, AuditLog.Action.STATUS, wo, changes={"status": {"from": before, "to": target}, **extra})


def _lock(wo: WorkOrder) -> WorkOrder:
    return WorkOrder.objects.select_for_update().select_related("asset", "asset__plant_unit__plant").get(pk=wo.pk)


def default_requires_verification(priority: str, asset: EquipmentAsset) -> bool:
    return priority in (WorkOrder.Priority.HIGH, WorkOrder.Priority.CRITICAL) or asset.criticality == EquipmentAsset.Criticality.HIGH


@transaction.atomic
def create_work_order(*, user, asset: EquipmentAsset, maintenance_type: str, title: str, description: str,
                      priority: str = WorkOrder.Priority.MEDIUM, reported_at: dt.datetime | None = None,
                      incident=None, requires_verification: bool | None = None, **planning) -> WorkOrder:
    if asset.is_archived:
        raise ValidationError({"asset": "Work orders cannot be raised on archived assets."})
    reported_at = reported_at or _now()
    _not_future(reported_at, "reported_at")
    if maintenance_type != WorkOrder.MaintenanceType.CORRECTIVE and not user.has_perm_code("workorders.manage"):
        raise ValidationError({"maintenance_type": "Only maintenance staff can raise planned maintenance work orders."})
    if incident is not None and incident.plant_unit_id != asset.plant_unit_id:
        raise ValidationError({"incident": "The incident belongs to a different plant unit."})
    if not user.has_perm_code("workorders.manage"):
        planning = {}  # fault reporters cannot plan or assign
    wo = WorkOrder(
        number=next_number("WO", year=reported_at.year), asset=asset, maintenance_type=maintenance_type, title=title,
        description=description, priority=priority, reported_at=reported_at, reported_by=user, incident=incident,
        requires_verification=(default_requires_verification(priority, asset)
                               if requires_verification is None else requires_verification),
        planned_start=planning.get("planned_start"), planned_end=planning.get("planned_end"),
        due_date=planning.get("due_date"), assigned_team=planning.get("assigned_team", ""),
    )
    _validate_planning(wo)
    wo.save()
    audit.record(user, AuditLog.Action.CREATE, wo, changes=audit.snapshot(wo))
    technician = planning.get("assigned_technician")
    if technician is not None:
        assign(wo, user=user, technician=technician, team=wo.assigned_team)
    return wo


def _validate_planning(wo: WorkOrder) -> None:
    if wo.planned_start and wo.planned_end and wo.planned_end < wo.planned_start:
        raise ValidationError({"planned_end": "Planned completion must be after the planned start."})


@transaction.atomic
def update_details(wo: WorkOrder, *, user, data: dict) -> WorkOrder:
    wo = _lock(wo)
    if not wo.is_open:
        raise ValidationError("Closed work orders cannot be edited.")
    allowed = {"title", "description", "priority", "planned_start", "planned_end", "assigned_team",
               "requires_verification", "root_cause", "failure_code"}
    unknown = set(data) - allowed
    if unknown:
        raise ValidationError(f"These fields cannot be changed here: {', '.join(sorted(unknown))}.")
    before = audit.snapshot(wo)
    for key, value in data.items():
        setattr(wo, key, value)
    _validate_planning(wo)
    wo.save()
    changes = audit.diff(before, audit.snapshot(wo))
    if changes:
        audit.record(user, AuditLog.Action.UPDATE, wo, changes=changes)
    return wo


@transaction.atomic
def assign(wo: WorkOrder, *, user, technician, team: str = "", planned_start=None, planned_end=None) -> WorkOrder:
    from apps.alerts.notify import notify
    from apps.workforce.models import Employee

    wo = _lock(wo)
    if technician is None and not team:
        raise ValidationError({"assigned_technician": "Assign a technician or a team."})
    if technician is not None and technician.employment_status != Employee.Status.ACTIVE:
        raise ValidationError({"assigned_technician": "The technician is not an active employee."})
    wo.assigned_technician = technician
    wo.assigned_team = team or wo.assigned_team
    if planned_start is not None:
        wo.planned_start = planned_start
    if planned_end is not None:
        wo.planned_end = planned_end
    _validate_planning(wo)
    if wo.status == S.REPORTED:
        _transition(wo, (S.REPORTED,), S.ASSIGNED, user,
                    assigned_to=technician.employee_code if technician else wo.assigned_team)
    elif wo.status in (S.ASSIGNED, S.IN_PROGRESS):
        wo.save()
        audit.record(user, AuditLog.Action.UPDATE, wo, message="Reassigned",
                     changes={"assigned_to": technician.employee_code if technician else wo.assigned_team})
    else:
        raise ValidationError(f"A work order that is '{wo.get_status_display()}' cannot be reassigned.")
    if technician is not None and technician.user is not None:
        notify([technician.user], f"Work order {wo.number} assigned to you", wo.title, f"/maintenance/work-orders/{wo.pk}")
    return wo


@transaction.atomic
def start(wo: WorkOrder, *, user, actual_start: dt.datetime | None = None) -> WorkOrder:
    wo = _lock(wo)
    actual_start = max(actual_start, wo.reported_at) if actual_start else _now()
    _not_future(actual_start, "actual_start")
    # Times are entered with minute precision, so compare at minute resolution.
    if actual_start < _minute(wo.reported_at):
        raise ValidationError({"actual_start": "Work cannot start before it was reported."})
    wo.actual_start = actual_start
    _transition(wo, (S.ASSIGNED,), S.IN_PROGRESS, user)
    return wo


@transaction.atomic
def complete(wo: WorkOrder, *, user, actions_performed: str, actual_end: dt.datetime | None = None,
             failure_code: str = "", root_cause: str = "", labor_hours: Decimal | None = None,
             completion_notes: str = "") -> WorkOrder:
    wo = _lock(wo)
    if wo.status != S.IN_PROGRESS:
        raise ValidationError("Only in-progress work orders can be completed.")
    actual_end = actual_end or _now()
    _not_future(actual_end, "actual_end")
    if actual_end < _minute(wo.actual_start):
        raise ValidationError({"actual_end": "Completion cannot be before the actual start."})
    actual_end = max(actual_end, wo.actual_start)
    if not actions_performed.strip():
        raise ValidationError({"actions_performed": "Describe the actions performed."})
    if wo.maintenance_type == WorkOrder.MaintenanceType.CORRECTIVE and not (failure_code or wo.failure_code):
        raise ValidationError({"failure_code": "Classify the failure (use 'Not established' if unknown)."})
    if labor_hours is not None and labor_hours < 0:
        raise ValidationError({"labor_hours": "Labour hours cannot be negative."})
    if wo.downtime_events.filter(ended_at__isnull=True).exists():
        raise ValidationError("Close the linked downtime event (enter the time the equipment returned to service) "
                              "before completing the work order.")
    wo.actual_end = actual_end
    wo.actions_performed = actions_performed
    wo.failure_code = failure_code or wo.failure_code
    wo.root_cause = root_cause or wo.root_cause
    wo.labor_hours = labor_hours if labor_hours is not None else wo.labor_hours
    wo.completion_notes = completion_notes
    wo.completed_by = user
    wo.is_blocked, wo.blocked_reason = False, ""
    target = S.AWAITING_VERIFICATION if wo.requires_verification else S.COMPLETED
    _transition(wo, (S.IN_PROGRESS,), target, user)
    if target == S.AWAITING_VERIFICATION:
        from apps.alerts.notify import notify_role

        notify_role("SUPERVISOR", f"Work order {wo.number} awaits verification", wo.title,
                    f"/maintenance/work-orders/{wo.pk}", exclude=user)
    return wo


@transaction.atomic
def verify(wo: WorkOrder, *, user, approve: bool, comment: str = "") -> WorkOrder:
    from apps.alerts.notify import notify

    wo = _lock(wo)
    if wo.status != S.AWAITING_VERIFICATION:
        raise ValidationError("This work order is not awaiting verification.")
    if wo.completed_by_id == user.pk:
        raise ValidationError("Work must be verified by someone other than the person who completed it.")
    if not approve and not comment.strip():
        raise ValidationError({"comment": "Explain what must be reworked."})
    snap = audit.snapshot(wo, fields={"actual_start", "actual_end", "actions_performed", "failure_code", "labor_hours"})
    if approve:
        wo.verified_by, wo.verified_at, wo.verification_comment = user, _now(), comment
        _transition(wo, (S.AWAITING_VERIFICATION,), S.COMPLETED, user)
        audit.record_approval(wo, action="VERIFY", actor=user, from_status=S.AWAITING_VERIFICATION,
                              to_status=S.COMPLETED, comment=comment, snap=snap)
    else:
        wo.actual_end = None
        wo.verification_comment = comment
        _transition(wo, (S.AWAITING_VERIFICATION,), S.IN_PROGRESS, user)
        audit.record_approval(wo, action="RETURN", actor=user, from_status=S.AWAITING_VERIFICATION,
                              to_status=S.IN_PROGRESS, comment=comment, snap=snap)
    if wo.completed_by:
        notify([wo.completed_by], f"Work order {wo.number} {'verified' if approve else 'returned for rework'}",
               comment, f"/maintenance/work-orders/{wo.pk}")
    return wo


@transaction.atomic
def cancel(wo: WorkOrder, *, user, reason: str) -> WorkOrder:
    from apps.inventory.models import StockTransaction

    wo = _lock(wo)
    if not reason.strip():
        raise ValidationError({"reason": "A cancellation reason is required."})
    if not wo.is_open:
        raise ValidationError("Only open work orders can be cancelled.")
    net = sum((t.quantity for t in StockTransaction.objects.filter(work_order=wo)), Decimal(0))
    if net < 0:
        raise ValidationError("Return the parts issued to this work order before cancelling it.")
    if wo.downtime_events.filter(ended_at__isnull=True).exists():
        raise ValidationError("Close the linked ongoing downtime event before cancelling.")
    wo.cancelled_reason, wo.cancelled_by, wo.cancelled_at = reason, user, _now()
    _transition(wo, WorkOrder.OPEN_STATUSES, S.CANCELLED, user, reason=reason)
    return wo


@transaction.atomic
def set_blocked(wo: WorkOrder, *, user, blocked: bool, reason: str = "") -> WorkOrder:
    wo = _lock(wo)
    if not wo.is_open:
        raise ValidationError("Closed work orders cannot be blocked.")
    if blocked and not reason.strip():
        raise ValidationError({"reason": "State what the work is waiting for."})
    wo.is_blocked, wo.blocked_reason = blocked, reason if blocked else ""
    wo.save(update_fields=["is_blocked", "blocked_reason", "updated_at"])
    audit.record(user, AuditLog.Action.UPDATE, wo, changes={"is_blocked": blocked, "reason": reason})
    return wo


WO_COST_CATEGORIES = ("LABOR", "CONTRACTOR", "EQUIPMENT_REPAIR", "OTHER")


@transaction.atomic
def add_cost(wo: WorkOrder, *, user, category: str, amount: Decimal, description: str,
             expense_date: dt.date | None = None, reference: str = "", cost_type: str = "ACTUAL"):
    from apps.costs.models import OperationalExpense
    from apps.costs.services import maintenance_department, validate_expense_amount

    wo = _lock(wo)
    if wo.status == S.CANCELLED:
        raise ValidationError("Costs cannot be added to a cancelled work order.")
    if category not in WO_COST_CATEGORIES:
        raise ValidationError({"category": "Parts are costed automatically when issued from stock. "
                                           f"Choose one of: {', '.join(WO_COST_CATEGORIES)}."})
    validate_expense_amount(amount)
    tz = plant_tz(wo.asset.plant_unit.plant)
    expense_date = expense_date or _now().astimezone(tz).date()
    if expense_date < wo.reported_at.astimezone(tz).date():
        raise ValidationError({"expense_date": "Cost date cannot be before the work order was reported."})
    if expense_date > timezone.now().astimezone(tz).date() and cost_type == "ACTUAL":
        raise ValidationError({"expense_date": "Actual costs cannot be dated in the future."})
    expense = OperationalExpense.objects.create(
        expense_date=expense_date, category=category, cost_type=cost_type, amount=amount,
        currency=get_setting("base_currency"), description=description[:255], reference=reference,
        asset=wo.asset, work_order=wo, plant_unit=wo.asset.plant_unit, source=OperationalExpense.Source.WORK_ORDER,
        department=maintenance_department(),
        recorded_by=user,
    )
    audit.record(user, AuditLog.Action.CREATE, expense, changes=audit.snapshot(expense))
    return expense


# --------------------------------------------------------------------------- downtime

_STATUS_FOR_TYPE = {
    DowntimeEvent.DowntimeType.PLANNED_MAINTENANCE: EquipmentAsset.Status.UNDER_MAINTENANCE,
}


def _overlap_exists(asset_id: int, start: dt.datetime, end: dt.datetime | None, exclude_pk=None) -> DowntimeEvent | None:
    qs = DowntimeEvent.objects.filter(asset_id=asset_id).filter(Q(ended_at__isnull=True) | Q(ended_at__gt=start))
    if end is not None:
        qs = qs.filter(started_at__lt=end)
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    return qs.first()


def _validate_window(asset_id: int, start: dt.datetime, end: dt.datetime | None, exclude_pk=None) -> None:
    _not_future(start, "started_at")
    _not_future(end, "ended_at")
    if end is not None and end <= start:
        raise ValidationError({"ended_at": "The end time must be after the start time."})
    clash = _overlap_exists(asset_id, start, end, exclude_pk)
    if clash is not None:
        ends = f"{timezone.localtime(clash.ended_at):%Y-%m-%d %H:%M}" if clash.ended_at else "ongoing"
        raise ValidationError({"started_at": (
            f"Overlaps an existing downtime event on this asset ({timezone.localtime(clash.started_at):%Y-%m-%d %H:%M}"
            f" to {ends}). Extend or correct that event instead of recording a second one."
        )})


def _sync_asset_status(asset: EquipmentAsset, user, *, opening: DowntimeEvent | None = None) -> None:
    if asset.is_archived:
        return
    before = asset.status
    if opening is not None:
        target = _STATUS_FOR_TYPE.get(opening.downtime_type, EquipmentAsset.Status.OUT_OF_SERVICE)
    elif not DowntimeEvent.objects.filter(asset=asset, ended_at__isnull=True).exists():
        target = EquipmentAsset.Status.OPERATIONAL
    else:
        return
    if target != before:
        asset.status = target
        asset.save(update_fields=["status", "updated_at"])
        audit.record(user, AuditLog.Action.STATUS, asset, changes={"status": {"from": before, "to": target}},
                     message="Updated from downtime record")


@transaction.atomic
def record_downtime(*, user, asset: EquipmentAsset, downtime_type: str, started_at: dt.datetime, cause: str,
                    ended_at: dt.datetime | None = None, work_order: WorkOrder | None = None, incident=None,
                    description: str = "") -> DowntimeEvent:
    asset = EquipmentAsset.objects.select_for_update().get(pk=asset.pk)  # serialise per-asset writes
    if asset.is_archived:
        raise ValidationError({"asset": "Downtime cannot be recorded on archived assets."})
    if work_order is not None and work_order.asset_id != asset.pk:
        raise ValidationError({"work_order": "The work order belongs to a different asset."})
    if work_order is not None and work_order.status == S.CANCELLED:
        raise ValidationError({"work_order": "The work order is cancelled."})
    if incident is not None and incident.plant_unit_id != asset.plant_unit_id:
        raise ValidationError({"incident": "The incident belongs to a different plant unit."})
    _validate_window(asset.pk, started_at, ended_at)
    try:
        with transaction.atomic():
            event = DowntimeEvent.objects.create(
                asset=asset, downtime_type=downtime_type, started_at=started_at, ended_at=ended_at, cause=cause,
                description=description, work_order=work_order, incident=incident, recorded_by=user,
            )
    except IntegrityError as exc:  # exclusion-constraint backstop
        raise ValidationError({"started_at": "Overlaps an existing downtime event on this asset."}) from exc
    audit.record(user, AuditLog.Action.CREATE, event, changes=audit.snapshot(event))
    if ended_at is None:
        _sync_asset_status(asset, user, opening=event)
    return event


@transaction.atomic
def update_downtime(event: DowntimeEvent, *, user, data: dict) -> DowntimeEvent:
    event = DowntimeEvent.objects.select_for_update().get(pk=event.pk)
    asset = EquipmentAsset.objects.select_for_update().get(pk=event.asset_id)
    allowed = {"downtime_type", "started_at", "ended_at", "cause", "description", "work_order", "incident"}
    unknown = set(data) - allowed
    if unknown:
        raise ValidationError(f"These fields cannot be changed: {', '.join(sorted(unknown))}.")
    wo = data.get("work_order", event.work_order)
    if wo is not None and wo.asset_id != asset.pk:
        raise ValidationError({"work_order": "The work order belongs to a different asset."})
    if event.work_order and event.work_order.status in WorkOrder.CLOSED_STATUSES and (
            "started_at" in data or "ended_at" in data or "work_order" in data):
        raise ValidationError("Downtime linked to a closed work order is locked. Ask maintenance to record a correction.")
    before = audit.snapshot(event)
    was_open = event.ended_at is None
    for key, value in data.items():
        setattr(event, key, value)
    _validate_window(asset.pk, event.started_at, event.ended_at, exclude_pk=event.pk)
    try:
        with transaction.atomic():
            event.save()
    except IntegrityError as exc:
        raise ValidationError({"started_at": "Overlaps an existing downtime event on this asset."}) from exc
    changes = audit.diff(before, audit.snapshot(event))
    if changes:
        audit.record(user, AuditLog.Action.UPDATE, event, changes=changes)
    if was_open and event.ended_at is not None:
        _sync_asset_status(asset, user)
    elif not was_open and event.ended_at is None:
        _sync_asset_status(asset, user, opening=event)
    return event


def close_downtime(event: DowntimeEvent, *, user, ended_at: dt.datetime | None = None) -> DowntimeEvent:
    if event.ended_at is not None:
        raise ValidationError("This downtime event is already closed.")
    return update_downtime(event, user=user, data={"ended_at": ended_at or _now()})


# --------------------------------------------------------------------------- preventive maintenance


def validate_schedule_start(start_date: dt.date, interval_days: int, today: dt.date) -> None:
    if start_date < today - dt.timedelta(days=interval_days):
        raise ValidationError({"start_date": "The first due date may be at most one interval in the past; "
                                             "otherwise a backlog of missed tasks would be generated."})


def generate_pm_work_orders(*, as_of: dt.date | None = None, schedules=None, user=None) -> list[WorkOrder]:
    """Create work orders for every scheduled due date within its lead time. Safe to run repeatedly."""
    created: list[WorkOrder] = []
    qs = schedules if schedules is not None else MaintenanceSchedule.objects.filter(is_active=True,
                                                                                    asset__archived_at__isnull=True)
    for schedule in qs.select_related("asset", "asset__plant_unit__plant", "default_technician"):
        tz = plant_tz(schedule.asset.plant_unit.plant)
        today = as_of or _now().astimezone(tz).date()
        with transaction.atomic():
            schedule = MaintenanceSchedule.objects.select_for_update().get(pk=schedule.pk)
            due = schedule.next_generation_due_date
            while due - dt.timedelta(days=schedule.lead_days) <= today:
                if not WorkOrder.objects.filter(schedule=schedule, due_date=due).exists():
                    created.append(_create_pm_work_order(schedule, due, tz, user or schedule.created_by))
                schedule.last_generated_due_date = due
                due = due + dt.timedelta(days=schedule.interval_days)
            schedule.save(update_fields=["last_generated_due_date", "updated_at"])
    return created


def _create_pm_work_order(schedule: MaintenanceSchedule, due: dt.date, tz, user) -> WorkOrder:
    planned_start = dt.datetime.combine(due, dt.time(8, 0), tzinfo=tz)
    wo = WorkOrder.objects.create(
        number=next_number("WO"), asset=schedule.asset, schedule=schedule, maintenance_type=schedule.task_type,
        title=schedule.title, description=schedule.description or schedule.title, priority=schedule.priority,
        status=S.ASSIGNED if schedule.default_technician else S.REPORTED, reported_at=_now(), reported_by=user,
        assigned_technician=schedule.default_technician, due_date=due, planned_start=planned_start,
        planned_end=dt.datetime.combine(due, dt.time(17, 0), tzinfo=tz), requires_verification=False,
    )
    audit.record(user, AuditLog.Action.CREATE, wo, message=f"Generated from schedule #{schedule.pk} for {due}")
    return wo


def pm_calendar(start: dt.date, end: dt.date, *, asset_ids=None, unit_id=None) -> list[dict]:
    """Generated PM work orders plus projected (not yet generated) due dates in [start, end]."""
    wos = WorkOrder.objects.filter(schedule__isnull=False, due_date__gte=start, due_date__lte=end).select_related(
        "asset", "schedule", "assigned_technician")
    schedules = MaintenanceSchedule.objects.filter(is_active=True, asset__archived_at__isnull=True).select_related("asset")
    if asset_ids:
        wos, schedules = wos.filter(asset_id__in=asset_ids), schedules.filter(asset_id__in=asset_ids)
    if unit_id:
        wos, schedules = wos.filter(asset__plant_unit_id=unit_id), schedules.filter(asset__plant_unit_id=unit_id)
    today = timezone.localdate()
    entries, generated = [], set()
    for wo in wos:
        generated.add((wo.schedule_id, wo.due_date))
        overdue = wo.is_open and wo.due_date < today
        entries.append({
            "date": wo.due_date.isoformat(), "kind": "work_order", "work_order_id": wo.pk, "number": wo.number,
            "title": wo.title, "asset_id": wo.asset_id, "asset_tag": wo.asset.asset_tag, "status": wo.status,
            "overdue": overdue, "technician": wo.assigned_technician.full_name if wo.assigned_technician else None,
        })
    for schedule in schedules:
        for due in schedule.due_dates_between(start, end):
            if (schedule.pk, due) in generated or (schedule.last_generated_due_date and due <= schedule.last_generated_due_date):
                continue
            entries.append({
                "date": due.isoformat(), "kind": "projected", "schedule_id": schedule.pk, "title": schedule.title,
                "asset_id": schedule.asset_id, "asset_tag": schedule.asset.asset_tag, "status": "PROJECTED",
                "overdue": False, "technician": None,
            })
    return sorted(entries, key=lambda e: (e["date"], e["asset_tag"]))
