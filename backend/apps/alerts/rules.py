"""Alert rule definitions.

Each rule is a pure *evaluator*: given its parameters and the current time it returns the
conditions that are true right now. The engine (engine.py) turns conditions into alerts,
deduplicates them, and clears alerts whose condition no longer holds. Thresholds come from
the AlertRule row (`params`), which administrators edit; the defaults below seed it.
"""
from __future__ import annotations

import calendar
import datetime as dt
import statistics
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable

from django.db.models import F, Q, Sum
from django.utils import timezone

from apps.accounts.roles import Role
from apps.core.period import plant_tz, resolve_plant
from apps.core.settings_registry import get_setting
from apps.core.timeutils import overlap_hours

from .models import Severity


@dataclass
class Condition:
    dedup_key: str
    title: str
    message: str
    link: str = ""
    related: Any = None
    severity: str | None = None
    context: dict = field(default_factory=dict)


@dataclass(frozen=True)
class RuleSpec:
    code: str
    name: str
    description: str
    severity: str
    defaults: dict
    audience: tuple[str, ...]
    evaluate: Callable[[dict, dt.datetime], list[Condition]]


def _fmt(value: Decimal | float, places: int = 1) -> str:
    return f"{Decimal(value):.{places}f}"


def _today(now: dt.datetime) -> dt.date:
    return now.astimezone(plant_tz(resolve_plant(None))).date()


# --------------------------------------------------------------------------- maintenance


def eval_excessive_downtime(params: dict, now: dt.datetime) -> list[Condition]:
    from apps.maintenance.models import DowntimeEvent

    out: list[Condition] = []
    ongoing_limit = Decimal(str(params["ongoing_hours"]))
    for ev in DowntimeEvent.objects.filter(ended_at__isnull=True).select_related("asset"):
        hours = overlap_hours(ev.started_at, None, ev.started_at, now)
        if hours >= ongoing_limit:
            out.append(Condition(
                dedup_key=f"ongoing:{ev.pk}",
                title=f"{ev.asset.asset_tag} down for {_fmt(hours)} h",
                message=(f"{ev.asset.name} has been unavailable since {timezone.localtime(ev.started_at):%Y-%m-%d %H:%M} "
                         f"({_fmt(hours)} h), exceeding the {ongoing_limit} h limit for a single outage. Cause: {ev.cause}."),
                link=f"/assets/{ev.asset_id}", related=ev.asset,
                severity=Severity.CRITICAL if ev.asset.criticality == "HIGH" else None,
                context={"hours": float(hours), "limit_hours": float(ongoing_limit), "event_id": ev.pk},
            ))
    window_start = now - dt.timedelta(days=int(params["window_days"]))
    limit = Decimal(str(params["max_hours"]))
    totals: dict[int, Decimal] = {}
    assets = {}
    for ev in DowntimeEvent.objects.filter(Q(ended_at__isnull=True) | Q(ended_at__gt=window_start),
                                           started_at__lt=now).select_related("asset"):
        totals[ev.asset_id] = totals.get(ev.asset_id, Decimal(0)) + overlap_hours(ev.started_at, ev.ended_at, window_start, now)
        assets[ev.asset_id] = ev.asset
    for asset_id, hours in totals.items():
        if hours > limit:
            asset = assets[asset_id]
            out.append(Condition(
                dedup_key=f"asset:{asset_id}",
                title=f"Excessive downtime on {asset.asset_tag}",
                message=(f"{asset.name} accumulated {_fmt(hours)} h of downtime in the last {params['window_days']} days, "
                         f"above the {limit} h threshold."),
                link=f"/maintenance/downtime?asset={asset_id}", related=asset,
                context={"hours": float(hours), "limit_hours": float(limit), "window_days": params["window_days"]},
            ))
    return out


def eval_pm_overdue(params: dict, now: dt.datetime) -> list[Condition]:
    from apps.maintenance.models import WorkOrder

    grace = get_setting("pm_compliance_grace_days")
    cutoff = _today(now) - dt.timedelta(days=grace)
    out = []
    for wo in WorkOrder.objects.filter(schedule__isnull=False, status__in=WorkOrder.OPEN_STATUSES,
                                       due_date__lt=cutoff).select_related("asset"):
        days = (_today(now) - wo.due_date).days
        out.append(Condition(
            dedup_key=f"wo:{wo.pk}",
            title=f"Preventive task overdue: {wo.number}",
            message=(f"'{wo.title}' on {wo.asset.asset_tag} was due {wo.due_date} and is {days} day(s) overdue "
                     f"(status: {wo.get_status_display()}; grace period {grace} day(s))."),
            link=f"/maintenance/work-orders/{wo.pk}", related=wo,
            severity=Severity.CRITICAL if days >= int(params["critical_after_days"]) else None,
            context={"days_overdue": days, "due_date": wo.due_date.isoformat()},
        ))
    return out


def eval_pm_upcoming(params: dict, now: dt.datetime) -> list[Condition]:
    from apps.maintenance.models import WorkOrder

    today = _today(now)
    out = []
    for wo in WorkOrder.objects.filter(schedule__isnull=False, status__in=[WorkOrder.Status.REPORTED, WorkOrder.Status.ASSIGNED],
                                       due_date__gte=today).select_related("asset", "schedule"):
        days = (wo.due_date - today).days
        if days <= wo.schedule.reminder_days:
            out.append(Condition(
                dedup_key=f"wo:{wo.pk}",
                title=f"Preventive task due in {days} day(s): {wo.number}",
                message=(f"'{wo.title}' on {wo.asset.asset_tag} is due {wo.due_date}. Reminder threshold: "
                         f"{wo.schedule.reminder_days} day(s) before due."),
                link=f"/maintenance/work-orders/{wo.pk}", related=wo, context={"days_to_due": days},
            ))
    return out


def eval_wo_overdue(params: dict, now: dt.datetime) -> list[Condition]:
    from apps.maintenance.models import WorkOrder

    out = []
    # Schedule-generated work orders are covered by PM_OVERDUE, so they are excluded to avoid double alerts.
    for wo in WorkOrder.objects.filter(schedule__isnull=True, status__in=WorkOrder.OPEN_STATUSES,
                                       planned_end__lt=now).select_related("asset"):
        hours = (now - wo.planned_end).total_seconds() / 3600
        out.append(Condition(
            dedup_key=f"wo:{wo.pk}",
            title=f"Work order overdue: {wo.number}",
            message=(f"'{wo.title}' on {wo.asset.asset_tag} was planned to finish "
                     f"{timezone.localtime(wo.planned_end):%Y-%m-%d %H:%M} and is {_fmt(hours)} h late "
                     f"(status: {wo.get_status_display()}{', blocked: ' + wo.blocked_reason if wo.is_blocked else ''})."),
            link=f"/maintenance/work-orders/{wo.pk}", related=wo,
            severity=Severity.CRITICAL if wo.priority == "CRITICAL" else None,
            context={"hours_late": round(hours, 1), "priority": wo.priority},
        ))
    return out


# --------------------------------------------------------------------------- inventory


def _stock_conditions(criticality: str) -> list[Condition]:
    from apps.inventory.models import InventoryItem

    out = []
    for item in InventoryItem.objects.filter(is_active=True, criticality=criticality,
                                             current_stock__lte=F("min_stock_level")):
        open_po = item.po_lines.filter(order__status__in=["ISSUED", "PARTIALLY_RECEIVED"]).aggregate(
            q=Sum(F("quantity_ordered") - F("quantity_received")))["q"]
        on_order = f" {open_po.normalize()} {item.uom} on order." if open_po else " Nothing is on order."
        out.append(Condition(
            dedup_key=f"item:{item.pk}",
            title=f"{'Critical spare' if criticality == 'CRITICAL' else 'Low stock'}: {item.item_code}",
            message=(f"{item.name}: {item.current_stock.normalize()} {item.uom} in stock, at or below the reorder point "
                     f"of {item.min_stock_level.normalize()} {item.uom}.{on_order}"),
            link=f"/inventory/items/{item.pk}", related=item,
            severity=Severity.CRITICAL if criticality == "CRITICAL" and item.current_stock <= 0 else None,
            context={"stock": str(item.current_stock), "min": str(item.min_stock_level),
                     "on_order": str(open_po) if open_po else "0"},
        ))
    return out


def eval_critical_stock(params: dict, now: dt.datetime) -> list[Condition]:
    return _stock_conditions("CRITICAL")


def eval_low_stock(params: dict, now: dt.datetime) -> list[Condition]:
    return _stock_conditions("STANDARD")


# --------------------------------------------------------------------------- approvals & reporting


def eval_pending_approvals(params: dict, now: dt.datetime) -> list[Condition]:
    from apps.inventory.models import PurchaseRequest
    from apps.maintenance.models import WorkOrder
    from apps.operations.models import OperationalReport

    out = []
    report_cutoff = now - dt.timedelta(hours=int(params["report_hours"]))
    for r in OperationalReport.objects.filter(status="SUBMITTED", submitted_at__lt=report_cutoff).select_related(
            "plant_unit", "shift"):
        hours = (now - r.submitted_at).total_seconds() / 3600
        out.append(Condition(
            dedup_key=f"report:{r.pk}", title=f"Report awaiting review for {_fmt(hours, 0)} h",
            message=f"{r} was submitted {timezone.localtime(r.submitted_at):%Y-%m-%d %H:%M} and has not been reviewed "
                    f"(threshold {params['report_hours']} h).",
            link=f"/operations/reports/{r.pk}", related=r, context={"hours_waiting": round(hours, 1)},
        ))
    other_cutoff = now - dt.timedelta(hours=int(params["other_hours"]))
    for pr in PurchaseRequest.objects.filter(status="SUBMITTED", submitted_at__lt=other_cutoff):
        out.append(Condition(
            dedup_key=f"pr:{pr.pk}", title=f"Purchase request {pr.pr_number} awaiting approval",
            message=f"Submitted {timezone.localtime(pr.submitted_at):%Y-%m-%d %H:%M}; threshold {params['other_hours']} h.",
            link=f"/procurement/requests/{pr.pk}", related=pr,
        ))
    for wo in WorkOrder.objects.filter(status="AWAITING_VERIFICATION", actual_end__lt=other_cutoff):
        out.append(Condition(
            dedup_key=f"wo-verify:{wo.pk}", title=f"{wo.number} awaiting verification",
            message=f"Completed {timezone.localtime(wo.actual_end):%Y-%m-%d %H:%M} and not yet verified "
                    f"(threshold {params['other_hours']} h).",
            link=f"/maintenance/work-orders/{wo.pk}", related=wo,
        ))
    return out


def eval_missing_reports(params: dict, now: dt.datetime) -> list[Condition]:
    from apps.operations.services import missing_reports

    today = _today(now)
    out = []
    for gap in missing_reports(today - dt.timedelta(days=int(params["lookback_days"])), today, now=now):
        state = "not submitted (draft)" if gap["state"] == "DRAFT_NOT_SUBMITTED" else "missing"
        out.append(Condition(
            dedup_key=f"{gap['plant_unit']}:{gap['shift']}:{gap['date']}",
            title=f"Shift report {state}: {gap['plant_unit_code']} {gap['date']} {gap['shift_name']}",
            message=(f"The {gap['shift_name']} report for {gap['plant_unit_code']} on {gap['date']} is {state}; "
                     f"it was due by {timezone.localtime(dt.datetime.fromisoformat(gap['deadline'])):%Y-%m-%d %H:%M}."),
            link=(f"/operations/reports/{gap['report_id']}" if gap["report_id"]
                  else f"/operations/reports/new?unit={gap['plant_unit']}&shift={gap['shift']}&date={gap['date']}"),
            context=gap,
        ))
    return out


def eval_metric_threshold(params: dict, now: dt.datetime) -> list[Condition]:
    from apps.operations.models import OperationalMeasurement

    since = _today(now) - dt.timedelta(days=int(params["lookback_days"]))
    out = []
    qs = (OperationalMeasurement.objects.filter(report__status__in=["SUBMITTED", "APPROVED"], report__report_date__gte=since,
                                                value__isnull=False)
          .filter(Q(metric__alert_low__isnull=False, value__lt=F("metric__alert_low")) |
                  Q(metric__alert_high__isnull=False, value__gt=F("metric__alert_high")))
          .select_related("metric", "report__plant_unit", "report__shift"))
    for m in qs:
        metric = m.metric
        side, bound = ("below", metric.alert_low) if metric.alert_low is not None and m.value < metric.alert_low else (
            "above", metric.alert_high)
        out.append(Condition(
            dedup_key=f"m:{m.pk}",
            title=f"{metric.name} {side} threshold on {m.report.plant_unit.code}",
            message=(f"{metric.name} was {m.value.normalize()} {metric.unit} for {m.report}, {side} the alert threshold of "
                     f"{bound.normalize()} {metric.unit}."),
            link=f"/operations/reports/{m.report_id}", related=m.report,
            context={"value": str(m.value), "threshold": str(bound), "side": side, "metric": metric.code},
        ))
    return out


def _month_add(day: dt.date, months: int) -> dt.date:
    """First day of the month `months` away from `day`'s month."""
    index = day.year * 12 + day.month - 1 + months
    return dt.date(index // 12, index % 12 + 1, 1)


def eval_expense_anomaly(params: dict, now: dt.datetime) -> list[Condition]:
    """Two checks on ACTUAL costs.

    1. Unusually large single expense: an invoice-type entry (manual or work-order cost, not an itemised stock
       issue - parts are valued by their item cost and vary by design) of at least `min_amount`, larger than
       `large_multiplier` x the 180-day median of its category (needs >= 5 earlier entries).
    2. Rapid increase: month-to-date spend in a category vs the average spend over the SAME days of the previous
       three months (like-for-like, so a bill that lands on the 5th of every month is not mistaken for a trend).
       Months before the start of the cost history are not used as a baseline.
    """
    from apps.costs.models import OperationalExpense

    today = _today(now)
    recent_from = today - dt.timedelta(days=int(params["lookback_days"]))
    history_from = today - dt.timedelta(days=180)
    actual = OperationalExpense.objects.filter(cost_type="ACTUAL", amount__gt=0)
    invoices = actual.exclude(source="STOCK")
    by_cat: dict[str, list[Decimal]] = {}
    for cat, amount in invoices.filter(expense_date__gte=history_from, expense_date__lt=recent_from).values_list("category", "amount"):
        by_cat.setdefault(cat, []).append(amount)
    out = []
    multiplier = Decimal(str(params["large_multiplier"]))
    min_amount = Decimal(str(params["min_amount"]))
    for exp in invoices.filter(expense_date__gte=recent_from, amount__gte=min_amount):
        history = by_cat.get(exp.category, [])
        if len(history) < 5:
            continue  # not enough history to call anything unusual
        median = Decimal(statistics.median(history))
        if exp.amount > median * multiplier:
            out.append(Condition(
                dedup_key=f"exp:{exp.pk}",
                title=f"Unusually large {exp.get_category_display().lower()} expense",
                message=(f"{exp.amount} {exp.currency} on {exp.expense_date} ('{exp.description}') is "
                         f"{_fmt(exp.amount / median)}x the 180-day median for this category ({_fmt(median, 2)})."),
                link=f"/costs/expenses?id={exp.pk}", related=exp,
                context={"amount": str(exp.amount), "median": str(median.quantize(Decimal('0.01')))},
            ))

    earliest = actual.order_by("expense_date").values_list("expense_date", flat=True).first()
    month_start = today.replace(day=1)
    baseline_months = [_month_add(month_start, -k) for k in (1, 2, 3)]
    if today.day < 10 or earliest is None or earliest > baseline_months[-1]:
        return out  # too early in the month, or not three full months of history
    current = dict(actual.filter(expense_date__gte=month_start, expense_date__lte=today)
                   .values_list("category").annotate(s=Sum("amount")))
    baseline: dict[str, Decimal] = {}
    for m in baseline_months:
        last_day = min(today.day, calendar.monthrange(m.year, m.month)[1])
        for cat, total in (actual.filter(expense_date__gte=m, expense_date__lte=m.replace(day=last_day))
                           .values_list("category").annotate(s=Sum("amount"))):
            baseline[cat] = baseline.get(cat, Decimal(0)) + total
    threshold = Decimal(str(params["mom_increase_pct"]))
    for cat, amount in current.items():
        if cat not in baseline or baseline[cat] <= 0 or amount < min_amount:
            continue
        avg = baseline[cat] / 3
        change = (amount - avg) / avg * 100
        if change >= threshold:
            out.append(Condition(
                dedup_key=f"trend:{cat}:{month_start:%Y-%m}",
                title=f"{cat.replace('_', ' ').title()} spending rising fast",
                message=(f"Spend from the 1st to the {today.day}th of this month is {_fmt(amount, 2)}, {_fmt(change, 0)}% above "
                         f"the average for the same days of the previous three months ({_fmt(avg, 2)}; threshold {threshold}%)."),
                link=f"/costs/expenses?category={cat}&date_from={month_start}",
                context={"month_to_date": str(amount), "baseline_same_days_avg": str(avg.quantize(Decimal('0.01'))),
                         "change_pct": float(change)},
            ))
    return out


ALL_ROLES = tuple(Role.values)
MAINT_AUD = (Role.MAINTENANCE, Role.SUPERVISOR, Role.MANAGEMENT, Role.ADMIN)

SPECS: dict[str, RuleSpec] = {s.code: s for s in [
    RuleSpec("EXCESSIVE_DOWNTIME", "Abnormal or excessive downtime",
             "An outage longer than `ongoing_hours`, or more than `max_hours` of downtime on one asset within the last "
             "`window_days` days.", Severity.WARNING, {"ongoing_hours": 8, "max_hours": 24, "window_days": 7}, MAINT_AUD,
             eval_excessive_downtime),
    RuleSpec("PM_OVERDUE", "Overdue preventive maintenance",
             "A schedule-generated work order is still open after its due date plus the PM grace period. Becomes "
             "critical after `critical_after_days`.", Severity.WARNING, {"critical_after_days": 7}, MAINT_AUD,
             eval_pm_overdue),
    RuleSpec("PM_UPCOMING", "Upcoming scheduled maintenance",
             "A preventive task that has not started is due within its schedule's reminder threshold.", Severity.INFO,
             {}, (Role.MAINTENANCE, Role.SUPERVISOR), eval_pm_upcoming),
    RuleSpec("WO_OVERDUE", "Overdue work orders",
             "An open corrective work order has passed its planned completion time.", Severity.WARNING, {}, MAINT_AUD,
             eval_wo_overdue),
    RuleSpec("CRITICAL_STOCK", "Critical spare-part shortage",
             "A spare classified as critical is at or below its reorder point. Critical severity when out of stock.",
             Severity.WARNING, {}, (Role.STORE, Role.MAINTENANCE, Role.MANAGEMENT, Role.ADMIN), eval_critical_stock),
    RuleSpec("LOW_STOCK", "Low stock",
             "A standard item is at or below its reorder point.", Severity.INFO, {}, (Role.STORE, Role.ADMIN),
             eval_low_stock),
    RuleSpec("PENDING_APPROVAL", "Pending approvals",
             "Operational reports waiting longer than `report_hours`, or purchase requests / work-order verifications "
             "waiting longer than `other_hours`.", Severity.INFO, {"report_hours": 12, "other_hours": 24},
             (Role.SUPERVISOR, Role.MANAGEMENT, Role.MAINTENANCE, Role.ADMIN), eval_pending_approvals),
    RuleSpec("MISSING_SHIFT_REPORT", "Incomplete shift reporting",
             "An expected shift report is missing or still in draft after its deadline, within the last `lookback_days`.",
             Severity.WARNING, {"lookback_days": 3}, (Role.OPERATIONS, Role.SUPERVISOR, Role.ADMIN), eval_missing_reports),
    RuleSpec("METRIC_THRESHOLD", "Operational metric outside threshold",
             "A submitted or approved measurement within the last `lookback_days` is outside the metric's alert range.",
             Severity.WARNING, {"lookback_days": 7}, (Role.OPERATIONS, Role.SUPERVISOR, Role.MANAGEMENT, Role.ADMIN),
             eval_metric_threshold),
    RuleSpec("EXPENSE_ANOMALY", "Unusual or rapidly increasing expenses",
             "An invoice-type actual expense of at least `min_amount` exceeds `large_multiplier` x its category's 180-day "
             "median, or a category's month-to-date spend is `mom_increase_pct`% above the average of the same days in the "
             "previous three months.",
             Severity.WARNING, {"lookback_days": 30, "large_multiplier": 3, "min_amount": 1000, "mom_increase_pct": 50},
             (Role.MANAGEMENT, Role.ADMIN), eval_expense_anomaly),
]}


def validate_params(code: str, params: dict) -> dict:
    """Only known numeric parameters are accepted; values must be positive."""
    from django.core.exceptions import ValidationError

    spec = SPECS[code]
    unknown = set(params) - set(spec.defaults)
    if unknown:
        raise ValidationError({"params": f"Unknown parameter(s): {', '.join(sorted(unknown))}."})
    clean = dict(spec.defaults)
    for key, value in params.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0 or value > 100000:
            raise ValidationError({"params": f"'{key}' must be a positive number."})
        clean[key] = value
    return clean
