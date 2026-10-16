"""Analytical calculations behind the dashboard, reports and BI reconciliation tests.

Every function reads database records; none returns invented values. Where a metric
cannot be computed honestly (no denominator, no timestamps) the function returns
`None` and the caller marks the KPI as `insufficient_data` rather than showing zero.
Monetary arithmetic is done in Decimal; values are rounded only at the API boundary.
"""
from __future__ import annotations

import calendar
import datetime as dt
from collections import defaultdict
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Count, F, Max, Q, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from apps.assets.models import EquipmentAsset
from apps.core.models import Plant, PlantUnit
from apps.core.settings_registry import get_setting
from apps.core.timeutils import Period, local_today, overlap_hours
from apps.costs.models import Budget, OperationalExpense
from apps.inventory.models import (
    GoodsReceiptLine,
    InventoryItem,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseRequest,
    StockTransaction,
)
from apps.maintenance.models import DowntimeEvent, WorkOrder
from apps.operations.models import MetricDefinition, OperationalIncident, OperationalMeasurement, OperationalReport
from apps.workforce.models import OvertimeRecord

ZERO = Decimal(0)
D2 = Decimal("0.01")
FAILURE = DowntimeEvent.DowntimeType.UNPLANNED_FAILURE


def r2(value: Decimal | float | None) -> float | None:
    if value is None:
        return None
    return float(Decimal(value).quantize(D2, rounding=ROUND_HALF_UP))


def pct(numerator, denominator) -> float | None:
    if not denominator:
        return None
    return r2(Decimal(numerator) * 100 / Decimal(denominator))


@dataclass
class Scope:
    period: Period
    plant: Plant | None = None
    unit: PlantUnit | None = None

    # Filters relative to a model's asset relation (e.g. prefix "asset__").
    def asset_q(self, prefix: str = "asset__") -> Q:
        if self.unit is not None:
            return Q(**{f"{prefix}plant_unit": self.unit})
        if self.plant is not None:
            return Q(**{f"{prefix}plant_unit__plant": self.plant})
        return Q()

    def unit_q(self, field: str = "plant_unit") -> Q:
        if self.unit is not None:
            return Q(**{field: self.unit})
        if self.plant is not None:
            return Q(**{f"{field}__plant": self.plant})
        return Q()

    def expense_q(self) -> Q:
        """Unit filter: expenses linked to the unit (directly or via asset). Plant filter additionally keeps
        plant-wide expenses with no unit or asset."""
        if self.unit is not None:
            return Q(plant_unit=self.unit) | Q(asset__plant_unit=self.unit)
        if self.plant is not None:
            return (Q(plant_unit__plant=self.plant) | Q(asset__plant_unit__plant=self.plant)
                    | Q(plant_unit__isnull=True, asset__isnull=True))
        return Q()

    @property
    def tz(self):
        return self.period.tz

    def query_string(self, **extra) -> str:
        params = {"date_from": self.period.date_from.isoformat(), "date_to": self.period.date_to.isoformat()}
        if self.unit:
            params["unit"] = str(self.unit.pk)
        params.update({k: str(v) for k, v in extra.items() if v is not None})
        return "&".join(f"{k}={v}" for k, v in params.items())


# --------------------------------------------------------------------------- downtime


def downtime_events(scope: Scope, types: list[str] | None = None):
    p = scope.period
    qs = (DowntimeEvent.objects.filter(scope.asset_q()).filter(started_at__lt=p.effective_end)
          .filter(Q(ended_at__isnull=True) | Q(ended_at__gt=p.start)).select_related("asset", "asset__category"))
    if types:
        qs = qs.filter(downtime_type__in=types)
    return qs


def downtime_hours(scope: Scope, types: list[str] | None = None) -> Decimal:
    p = scope.period
    return sum((overlap_hours(e.started_at, e.ended_at, p.start, p.effective_end) for e in downtime_events(scope, types)), ZERO)


def _bucket_key(day: dt.date, granularity: str) -> dt.date:
    if granularity == "week":
        return day - dt.timedelta(days=day.weekday())
    if granularity == "month":
        return day.replace(day=1)
    return day


def downtime_trend(scope: Scope, granularity: str = "day") -> list[dict]:
    p = scope.period
    buckets: dict[dt.date, dict[str, Decimal]] = {}
    day = p.date_from
    while day <= p.date_to:
        buckets.setdefault(_bucket_key(day, granularity), defaultdict(Decimal))
        day += dt.timedelta(days=1)
    for e in downtime_events(scope):
        start = max(e.started_at, p.start)
        end = min(e.ended_at or p.effective_end, p.effective_end)
        cursor = start.astimezone(p.tz).date()
        while True:
            day_start = dt.datetime.combine(cursor, dt.time.min, tzinfo=p.tz)
            day_end = day_start + dt.timedelta(days=1)
            if day_start >= end:
                break
            hours = overlap_hours(start, end, day_start, day_end)
            if hours:
                buckets[_bucket_key(cursor, granularity)][e.downtime_type] += hours
            cursor += dt.timedelta(days=1)
    rows = []
    for key in sorted(buckets):
        values = buckets[key]
        rows.append({
            "bucket": key.isoformat(),
            **{t.lower(): r2(values.get(t, ZERO)) for t in DowntimeEvent.DowntimeType.values},
            "total": r2(sum(values.values(), ZERO)),
        })
    return rows


def top_assets_by_downtime(scope: Scope, limit: int = 10) -> list[dict]:
    p = scope.period
    totals: dict[int, Decimal] = defaultdict(Decimal)
    counts: dict[int, int] = defaultdict(int)
    assets = {}
    for e in downtime_events(scope):
        totals[e.asset_id] += overlap_hours(e.started_at, e.ended_at, p.start, p.effective_end)
        counts[e.asset_id] += 1
        assets[e.asset_id] = e.asset
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    return [{"asset_id": aid, "asset_tag": assets[aid].asset_tag, "name": assets[aid].name, "hours": r2(h),
             "events": counts[aid]} for aid, h in ranked]


def failures_in_period(scope: Scope):
    p = scope.period
    return DowntimeEvent.objects.filter(scope.asset_q(), downtime_type=FAILURE, started_at__gte=p.start,
                                        started_at__lt=p.effective_end).select_related("asset__category")


def failures_by_category(scope: Scope) -> list[dict]:
    p = scope.period
    data: dict[int, dict] = {}
    for e in failures_in_period(scope):
        cat = e.asset.category
        row = data.setdefault(cat.pk, {"category_id": cat.pk, "category": cat.name, "failures": 0, "hours": ZERO})
        row["failures"] += 1
        row["hours"] += overlap_hours(e.started_at, e.ended_at, p.start, p.effective_end)
    return sorted(({**r, "hours": r2(r["hours"])} for r in data.values()), key=lambda r: r["failures"], reverse=True)


def mttr(scope: Scope) -> dict:
    p = scope.period
    events = DowntimeEvent.objects.filter(scope.asset_q(), downtime_type=FAILURE, ended_at__gte=p.start,
                                          ended_at__lt=p.effective_end)
    durations = [Decimal((e.ended_at - e.started_at).total_seconds()) / 3600 for e in events]
    if not durations:
        return {"value": None, "status": "insufficient_data", "events": 0}
    return {"value": r2(sum(durations, ZERO) / len(durations)), "status": "ok", "events": len(durations)}


def assets_in_scope(scope: Scope):
    p = scope.period
    return EquipmentAsset.objects.filter(scope.unit_q("plant_unit")).filter(
        Q(archived_at__isnull=True) | Q(archived_at__gte=p.start)).filter(
        Q(commissioned_on__isnull=True) | Q(commissioned_on__lte=p.date_to))


def mtbf(scope: Scope) -> dict:
    failures = failures_in_period(scope).count()
    n_assets = assets_in_scope(scope).count()
    if failures == 0 or n_assets == 0:
        return {"value": None, "status": "insufficient_data", "failures": failures, "assets": n_assets}
    uptime = Decimal(n_assets) * scope.period.elapsed_hours - downtime_hours(scope)
    return {"value": r2(uptime / failures), "status": "low_confidence" if failures < 3 else "ok",
            "failures": failures, "assets": n_assets, "uptime_hours": r2(uptime)}


def repeat_failures(scope: Scope) -> dict:
    window = dt.timedelta(days=get_setting("repeat_failure_window_days"))
    p = scope.period
    events = (DowntimeEvent.objects.filter(scope.asset_q(), downtime_type=FAILURE, started_at__gte=p.start - window,
                                           started_at__lt=p.effective_end).order_by("asset_id", "started_at")
              .select_related("asset"))
    previous: dict[int, dt.datetime] = {}
    total = repeats = 0
    repeat_assets: dict[int, dict] = {}
    for e in events:
        in_period = e.started_at >= p.start
        prev = previous.get(e.asset_id)
        if in_period:
            total += 1
            if prev is not None and e.started_at - prev <= window:
                repeats += 1
                row = repeat_assets.setdefault(e.asset_id, {"asset_id": e.asset_id, "asset_tag": e.asset.asset_tag,
                                                            "name": e.asset.name, "repeats": 0})
                row["repeats"] += 1
        previous[e.asset_id] = e.started_at
    return {"failures": total, "repeats": repeats, "value": pct(repeats, total),
            "status": "ok" if total else "insufficient_data",
            "assets": sorted(repeat_assets.values(), key=lambda r: r["repeats"], reverse=True)[:10],
            "window_days": window.days}


# --------------------------------------------------------------------------- work orders


def overdue_q(now: dt.datetime, today: dt.date) -> Q:
    grace = get_setting("pm_compliance_grace_days")
    return Q(status__in=WorkOrder.OPEN_STATUSES) & (
        Q(schedule__isnull=True, planned_end__lt=now) |
        Q(schedule__isnull=False, due_date__lt=today - dt.timedelta(days=grace)))


def work_order_snapshot(scope: Scope) -> dict:
    qs = WorkOrder.objects.filter(scope.asset_q())
    now = timezone.now()
    today = local_today(scope.tz)
    return {
        "open": qs.filter(status__in=WorkOrder.OPEN_STATUSES).count(),
        "overdue": qs.filter(overdue_q(now, today)).count(),
        "blocked": qs.filter(status__in=WorkOrder.OPEN_STATUSES, is_blocked=True).count(),
        "awaiting_verification": qs.filter(status=WorkOrder.Status.AWAITING_VERIFICATION).count(),
    }


def work_orders_reported(scope: Scope):
    p = scope.period
    return WorkOrder.objects.filter(scope.asset_q(), reported_at__gte=p.start, reported_at__lt=p.end)


def work_order_status_distribution(scope: Scope) -> list[dict]:
    counts = dict(work_orders_reported(scope).values_list("status").annotate(n=Count("id")))
    return [{"status": s, "label": WorkOrder.Status(s).label, "count": counts.get(s, 0)} for s in WorkOrder.Status.values]


def maintenance_mix(scope: Scope) -> dict:
    qs = work_orders_reported(scope)
    totals = dict(qs.values_list("maintenance_type").annotate(n=Count("id")))
    monthly = defaultdict(lambda: {t: 0 for t in WorkOrder.MaintenanceType.values})
    for month, mtype, n in (qs.annotate(m=TruncMonth("reported_at", tzinfo=scope.tz)).values_list("m", "maintenance_type")
                            .annotate(n=Count("id"))):
        monthly[month.date().isoformat()][mtype] = n
    planned = totals.get("PREVENTIVE", 0) + totals.get("INSPECTION", 0)
    return {
        "totals": {t: totals.get(t, 0) for t in WorkOrder.MaintenanceType.values},
        "planned_pct": pct(planned, sum(totals.values())),
        "monthly": [{"month": k, **{t.lower(): v for t, v in row.items()}} for k, row in sorted(monthly.items())],
    }


def pm_compliance(scope: Scope) -> dict:
    p = scope.period
    grace = dt.timedelta(days=get_setting("pm_compliance_grace_days"))
    today = local_today(p.tz)
    tasks = WorkOrder.objects.filter(scope.asset_q(), schedule__isnull=False, due_date__gte=p.date_from,
                                     due_date__lte=p.date_to).select_related("asset__plant_unit__plant")
    due = compliant = late = missed = cancelled = 0
    for wo in tasks:
        deadline = wo.due_date + grace
        completed = wo.status == WorkOrder.Status.COMPLETED
        if not completed and deadline >= today:
            continue  # still within its window: not yet assessable
        due += 1
        if completed and wo.actual_end.astimezone(p.tz).date() <= deadline:
            compliant += 1
        elif completed:
            late += 1
        elif wo.status == WorkOrder.Status.CANCELLED:
            cancelled += 1
        else:
            missed += 1
    return {"value": pct(compliant, due), "status": "ok" if due else "insufficient_data", "due": due,
            "compliant": compliant, "completed_late": late, "not_completed": missed, "cancelled": cancelled,
            "grace_days": grace.days}


def wo_completion_rate(scope: Scope) -> dict:
    qs = work_orders_reported(scope).exclude(status=WorkOrder.Status.CANCELLED)
    total = qs.count()
    done = qs.filter(status=WorkOrder.Status.COMPLETED).count()
    return {"value": pct(done, total), "status": "ok" if total else "insufficient_data", "completed": done, "total": total}


def avg_repair_cost(scope: Scope) -> dict:
    p = scope.period
    wos = WorkOrder.objects.filter(scope.asset_q(), maintenance_type=WorkOrder.MaintenanceType.CORRECTIVE,
                                   status=WorkOrder.Status.COMPLETED, actual_end__gte=p.start, actual_end__lt=p.end)
    n = wos.count()
    if n == 0:
        return {"value": None, "status": "insufficient_data", "work_orders": 0}
    total = OperationalExpense.objects.filter(work_order__in=wos, cost_type="ACTUAL").aggregate(s=Sum("amount"))["s"] or ZERO
    return {"value": r2(total / n), "status": "ok", "work_orders": n, "total_cost": r2(total)}


def work_order_costs(wo: WorkOrder) -> dict:
    rows = dict(OperationalExpense.objects.filter(work_order=wo, cost_type="ACTUAL").values_list("category")
                .annotate(s=Sum("amount")))
    parts = rows.get("SPARE_PARTS", ZERO) + rows.get("CONSUMABLES", ZERO)
    labor = rows.get("LABOR", ZERO)
    other = sum(rows.values(), ZERO) - parts - labor
    return {"parts": r2(parts), "labor": r2(labor), "other": r2(other), "total": r2(parts + labor + other)}


# --------------------------------------------------------------------------- costs


def actual_expenses(scope: Scope):
    p = scope.period
    return OperationalExpense.objects.filter(scope.expense_q(), cost_type="ACTUAL", expense_date__gte=p.date_from,
                                             expense_date__lte=p.date_to)


MAINTENANCE_Q = Q(work_order__isnull=False) | Q(asset__isnull=False)


def maintenance_cost(scope: Scope) -> Decimal:
    return actual_expenses(scope).filter(MAINTENANCE_Q).aggregate(s=Sum("amount"))["s"] or ZERO


def operating_cost(scope: Scope) -> Decimal:
    return actual_expenses(scope).aggregate(s=Sum("amount"))["s"] or ZERO


def _month_starts(p: Period) -> list[dt.date]:
    months, cursor = [], p.date_from.replace(day=1)
    while cursor <= p.date_to:
        months.append(cursor)
        cursor = (cursor.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return months


def _days_in_period_for_month(p: Period, month: dt.date) -> int:
    last = month.replace(day=calendar.monthrange(month.year, month.month)[1])
    start, end = max(p.date_from, month), min(p.date_to, last)
    return max((end - start).days + 1, 0)


def prorated_budgets(scope: Scope, *, maintenance_only: bool = False) -> dict[tuple[dt.date, str], Decimal]:
    """Budget per (month, category), prorated to the share of each month inside the period."""
    p = scope.period
    out: dict[tuple[dt.date, str], Decimal] = defaultdict(Decimal)
    months = _month_starts(p)
    qs = Budget.objects.filter(Q(*[Q(year=m.year, month=m.month) for m in months], _connector=Q.OR)) if months else Budget.objects.none()
    if maintenance_only:
        qs = qs.filter(department__code=get_setting("maintenance_department_code"))
    for b in qs:
        month = dt.date(b.year, b.month, 1)
        dim = calendar.monthrange(b.year, b.month)[1]
        out[(month, b.category)] += b.amount * Decimal(_days_in_period_for_month(p, month)) / Decimal(dim)
    return out


def cost_by_month(scope: Scope, *, maintenance_only: bool = False) -> list[dict]:
    qs = actual_expenses(scope)
    if maintenance_only:
        qs = qs.filter(MAINTENANCE_Q)
    actual = dict(qs.annotate(m=TruncMonth("expense_date")).values_list("m").annotate(s=Sum("amount")))
    budgets = prorated_budgets(scope, maintenance_only=maintenance_only)
    budget_by_month: dict[dt.date, Decimal] = defaultdict(Decimal)
    for (month, _cat), amount in budgets.items():
        budget_by_month[month] += amount
    has_budget = bool(budgets)
    rows = []
    for month in _month_starts(scope.period):
        a = actual.get(month, ZERO)
        b = budget_by_month.get(month) if has_budget else None
        rows.append({"month": month.isoformat(), "actual": r2(a), "budget": r2(b) if b is not None else None,
                     "variance": r2(a - b) if b is not None else None})
    return rows


def cost_by_category(scope: Scope) -> list[dict]:
    actual = dict(actual_expenses(scope).values_list("category").annotate(s=Sum("amount")))
    budgets: dict[str, Decimal] = defaultdict(Decimal)
    for (_m, cat), amount in prorated_budgets(scope).items():
        budgets[cat] += amount
    from apps.costs.models import CostCategory

    rows = []
    for cat in CostCategory.values:
        a, b = actual.get(cat, ZERO), budgets.get(cat)
        if a == 0 and b is None:
            continue
        rows.append({"category": cat, "label": CostCategory(cat).label, "actual": r2(a),
                     "budget": r2(b) if b is not None else None, "variance": r2(a - b) if b is not None else None,
                     "variance_pct": pct(a - b, b) if b else None})
    return sorted(rows, key=lambda r: r["actual"], reverse=True)


def cost_by_asset(scope: Scope, limit: int = 10) -> list[dict]:
    rows = (actual_expenses(scope).filter(asset__isnull=False).values("asset_id", "asset__asset_tag", "asset__name")
            .annotate(total=Sum("amount"), work_orders=Count("work_order", distinct=True)).order_by("-total")[:limit])
    return [{"asset_id": r["asset_id"], "asset_tag": r["asset__asset_tag"], "name": r["asset__name"],
             "total": r2(r["total"]), "work_orders": r["work_orders"]} for r in rows]


def cost_by_department(scope: Scope) -> list[dict]:
    rows = actual_expenses(scope).values("department_id", "department__name").annotate(total=Sum("amount")).order_by("-total")
    return [{"department_id": r["department_id"], "department": r["department__name"] or "Unassigned",
             "total": r2(r["total"])} for r in rows]


def cost_by_unit(scope: Scope) -> list[dict]:
    rows = (actual_expenses(scope).annotate(unit_code=F("plant_unit__code")).values("plant_unit_id", "unit_code")
            .annotate(total=Sum("amount")).order_by("-total"))
    return [{"plant_unit_id": r["plant_unit_id"], "unit": r["unit_code"] or "Plant-wide", "total": r2(r["total"])}
            for r in rows]


def budget_variance(scope: Scope) -> dict:
    budgets = prorated_budgets(scope)
    if not budgets:
        return {"value": None, "status": "insufficient_data", "budget": None, "actual": r2(operating_cost(scope))}
    budget = sum(budgets.values(), ZERO)
    actual = operating_cost(scope)
    return {"value": r2(actual - budget), "status": "ok", "budget": r2(budget), "actual": r2(actual),
            "variance_pct": pct(actual - budget, budget)}


def expense_anomalies() -> list[dict]:
    from apps.alerts.models import AlertRule
    from apps.alerts.rules import SPECS, eval_expense_anomaly

    rule = AlertRule.objects.filter(code="EXPENSE_ANOMALY").first()
    params = {**SPECS["EXPENSE_ANOMALY"].defaults, **(rule.params if rule else {})}
    return [{"key": c.dedup_key, "title": c.title, "message": c.message, "link": c.link, "context": c.context}
            for c in eval_expense_anomaly(params, timezone.now())]


# --------------------------------------------------------------------------- inventory


def stock_snapshot() -> dict:
    items = InventoryItem.objects.filter(is_active=True)
    low = items.filter(current_stock__lte=F("min_stock_level"))
    valuation = sum((i.current_stock * i.unit_cost for i in items.only("current_stock", "unit_cost")), ZERO)
    statuses = defaultdict(int)
    for item in items.only("current_stock", "min_stock_level", "criticality"):
        statuses[item.stock_status] += 1
    return {
        "items": items.count(),
        "low": low.count(),
        "critical_low": low.filter(criticality=InventoryItem.Criticality.CRITICAL).count(),
        "out_of_stock": items.filter(current_stock__lte=0).count(),
        "valuation": r2(valuation),
        "status_counts": [{"status": s, "count": statuses.get(s, 0)} for s in ["OK", "LOW", "CRITICAL_LOW", "OUT_OF_STOCK"]],
    }


def reorder_watchlist(limit: int = 12) -> list[dict]:
    items = InventoryItem.objects.filter(is_active=True, min_stock_level__gt=0).select_related("category")
    rows = []
    for i in items:
        coverage = i.current_stock / i.min_stock_level
        rows.append({"item_id": i.pk, "item_code": i.item_code, "name": i.name, "stock": float(i.current_stock),
                     "min": float(i.min_stock_level), "coverage_pct": r2(coverage * 100), "status": i.stock_status,
                     "criticality": i.criticality, "uom": i.uom})
    return sorted(rows, key=lambda r: r["coverage_pct"])[:limit]


def ledger_value_at(moment: dt.datetime) -> Decimal:
    return StockTransaction.objects.filter(occurred_at__lt=moment).aggregate(s=Sum("total_value"))["s"] or ZERO


def consumption(scope: Scope):
    p = scope.period
    return StockTransaction.objects.filter(txn_type__in=["ISSUE", "RETURN"], occurred_at__gte=p.start, occurred_at__lt=p.end)


def consumption_by_month(scope: Scope) -> list[dict]:
    """Net value issued per month (issues minus returns), at the cost recorded on each movement."""
    rows = {m.date(): v for m, v in consumption(scope).annotate(m=TruncMonth("occurred_at", tzinfo=scope.tz))
            .values_list("m").annotate(v=Sum("total_value"))}
    return [{"month": month.isoformat(), "value": r2(-rows.get(month, ZERO))} for month in _month_starts(scope.period)]


def inventory_turnover(scope: Scope) -> dict:
    p = scope.period
    issued = -(consumption(scope).aggregate(s=Sum("total_value"))["s"] or ZERO)
    start_value, end_value = ledger_value_at(p.start), ledger_value_at(p.effective_end)
    avg_value = (start_value + end_value) / 2
    if p.days < 28 or avg_value <= 0:
        return {"value": None, "status": "insufficient_data", "issued_value": r2(issued), "avg_stock_value": r2(avg_value)}
    turns = issued / avg_value * Decimal(365) / Decimal(p.days)
    return {"value": r2(turns), "status": "ok", "issued_value": r2(issued), "avg_stock_value": r2(avg_value),
            "opening_value": r2(start_value), "closing_value": r2(end_value)}


def slow_moving_items(limit: int = 50) -> list[dict]:
    days = get_setting("slow_moving_days")
    cutoff = timezone.now() - dt.timedelta(days=days)
    last_issue = dict(StockTransaction.objects.filter(txn_type="ISSUE").values_list("item_id").annotate(m=Max("occurred_at")))
    rows = []
    for i in InventoryItem.objects.filter(is_active=True, current_stock__gt=0):
        last = last_issue.get(i.pk)
        if last is None or last < cutoff:
            rows.append({"item_id": i.pk, "item_code": i.item_code, "name": i.name, "stock": float(i.current_stock),
                         "value": r2(i.current_stock * i.unit_cost), "last_issue_at": last.isoformat() if last else None,
                         "uom": i.uom})
    return sorted(rows, key=lambda r: r["value"], reverse=True)[:limit]


def purchase_spend(scope: Scope) -> Decimal:
    p = scope.period
    lines = GoodsReceiptLine.objects.filter(receipt__received_at__gte=p.start, receipt__received_at__lt=p.end)
    return sum((l.quantity * l.order_line.unit_price for l in lines.select_related("order_line")), ZERO)


def open_commitments() -> Decimal:
    lines = PurchaseOrderLine.objects.filter(order__status__in=["ISSUED", "PARTIALLY_RECEIVED"])
    return sum(((l.quantity_ordered - l.quantity_received) * l.unit_price for l in lines), ZERO)


def supplier_lead_times(scope: Scope) -> dict:
    p = scope.period
    orders = PurchaseOrder.objects.filter(fully_received_at__gte=p.start, fully_received_at__lt=p.end,
                                          order_date__isnull=False).select_related("supplier")
    per_supplier: dict[int, dict] = {}
    all_days = []
    for po in orders:
        days = (po.fully_received_at.astimezone(p.tz).date() - po.order_date).days
        all_days.append(days)
        row = per_supplier.setdefault(po.supplier_id, {"supplier_id": po.supplier_id, "supplier": po.supplier.name,
                                                       "orders": 0, "days": [], "on_time": 0,
                                                       "quoted": po.supplier.quoted_lead_time_days})
        row["orders"] += 1
        row["days"].append(days)
        if po.expected_delivery_date and po.fully_received_at.astimezone(p.tz).date() <= po.expected_delivery_date:
            row["on_time"] += 1
    suppliers = [{**{k: v for k, v in r.items() if k != "days"}, "avg_days": r2(Decimal(sum(r["days"])) / len(r["days"])),
                  "on_time_pct": pct(r["on_time"], r["orders"])} for r in per_supplier.values()]
    return {"value": r2(Decimal(sum(all_days)) / len(all_days)) if all_days else None,
            "status": "ok" if all_days else "insufficient_data", "orders": len(all_days),
            "suppliers": sorted(suppliers, key=lambda r: r["avg_days"] or 0, reverse=True)}


# --------------------------------------------------------------------------- operations


def primary_metric(scope: Scope) -> MetricDefinition | None:
    plant = scope.unit.plant if scope.unit else scope.plant
    if plant is None:
        return None
    return MetricDefinition.objects.filter(plant=plant, is_primary_output=True, is_active=True).first()


def approved_measurements(scope: Scope, metric: MetricDefinition):
    p = scope.period
    return OperationalMeasurement.objects.filter(
        scope.unit_q("report__plant_unit"), metric=metric, report__status=OperationalReport.Status.APPROVED,
        report__report_date__gte=p.date_from, report__report_date__lte=p.date_to)


def metric_aggregate(scope: Scope, metric: MetricDefinition) -> dict:
    qs = approved_measurements(scope, metric)
    values = list(qs.filter(value__isnull=False).values_list("value", flat=True))
    missing = qs.filter(value__isnull=True).count()
    if not values:
        return {"value": None, "status": "insufficient_data", "reports": 0, "missing": missing, "unit": metric.unit,
                "target": None, "vs_target_pct": None}
    total = sum(values, ZERO)
    value = total if metric.aggregation == MetricDefinition.Aggregation.SUM else total / len(values)
    target = None
    if metric.target_value is not None:
        target = metric.target_value * len(values) if metric.aggregation == MetricDefinition.Aggregation.SUM else metric.target_value
    return {"value": r2(value), "status": "ok", "reports": len(values), "missing": missing, "unit": metric.unit,
            "target": r2(target), "vs_target_pct": pct(value, target) if target else None}


def metric_trend(scope: Scope, metric: MetricDefinition) -> list[dict]:
    qs = approved_measurements(scope, metric).filter(value__isnull=False)
    by_day: dict[dt.date, list[Decimal]] = defaultdict(list)
    for day, value in qs.values_list("report__report_date", "value"):
        by_day[day].append(value)
    rows = []
    day = scope.period.date_from
    while day <= scope.period.date_to:
        vals = by_day.get(day)
        if vals:
            is_sum = metric.aggregation == "SUM"
            v = sum(vals, ZERO) if is_sum else sum(vals, ZERO) / len(vals)
            t = None
            if metric.target_value is not None:
                t = metric.target_value * len(vals) if is_sum else metric.target_value
        else:
            v = t = None  # no approved data that day: a gap, not zero
        rows.append({"date": day.isoformat(), "value": r2(v), "target": r2(t), "reports": len(vals or [])})
        day += dt.timedelta(days=1)
    return rows


def metric_by_shift(scope: Scope, metric: MetricDefinition) -> list[dict]:
    qs = approved_measurements(scope, metric).filter(value__isnull=False)
    rows = qs.values("report__shift_id", "report__shift__name", "report__shift__sequence").annotate(
        total=Sum("value"), n=Count("id")).order_by("report__shift__sequence")
    return [{"shift_id": r["report__shift_id"], "shift": r["report__shift__name"], "total": r2(r["total"]),
             "per_report": r2(r["total"] / r["n"]), "reports": r["n"]} for r in rows]


def incidents_by_shift(scope: Scope) -> list[dict]:
    """Incidents recorded on shift reports in the period, grouped by the report's shift."""
    p = scope.period
    rows = (OperationalIncident.objects.filter(scope.unit_q(), occurred_at__gte=p.start, occurred_at__lt=p.end,
                                               report__isnull=False)
            .values("report__shift__name", "report__shift__sequence").annotate(n=Count("id")).order_by("report__shift__sequence"))
    return [{"shift": r["report__shift__name"], "incidents": r["n"]} for r in rows]


def report_status_counts(scope: Scope) -> dict:
    p = scope.period
    qs = OperationalReport.objects.filter(scope.unit_q(), report_date__gte=p.date_from, report_date__lte=p.date_to)
    return dict(qs.values_list("status").annotate(n=Count("id")))


def pending_approvals() -> dict:
    parts = {
        "operational_reports": OperationalReport.objects.filter(status="SUBMITTED").count(),
        "purchase_requests": PurchaseRequest.objects.filter(status="SUBMITTED").count(),
        "work_order_verifications": WorkOrder.objects.filter(status="AWAITING_VERIFICATION").count(),
        "overtime": OvertimeRecord.objects.filter(status="PENDING").count(),
    }
    return {"value": sum(parts.values()), "breakdown": parts}


def open_incidents(scope: Scope) -> dict:
    qs = OperationalIncident.objects.filter(scope.unit_q()).exclude(status=OperationalIncident.Status.RESOLVED)
    by_sev = dict(qs.values_list("severity").annotate(n=Count("id")))
    return {"value": qs.count(), "by_severity": by_sev}


def freshness() -> dict:
    def iso(v):
        return v.isoformat() if v else None

    return {
        "generated_at": timezone.now().isoformat(),
        "last_approved_report_at": iso(OperationalReport.objects.filter(status="APPROVED").aggregate(m=Max("reviewed_at"))["m"]),
        "last_work_order_update_at": iso(WorkOrder.objects.aggregate(m=Max("updated_at"))["m"]),
        "last_downtime_update_at": iso(DowntimeEvent.objects.aggregate(m=Max("updated_at"))["m"]),
        "last_stock_movement_at": iso(StockTransaction.objects.aggregate(m=Max("occurred_at"))["m"]),
        "last_expense_at": iso(OperationalExpense.objects.aggregate(m=Max("created_at"))["m"]),
    }


# --------------------------------------------------------------------------- asset detail


def asset_summary(asset: EquipmentAsset) -> dict:
    now = timezone.now()
    events = list(asset.downtime_events.all())
    lifetime = sum((overlap_hours(e.started_at, e.ended_at, e.started_at, now) for e in events), ZERO)
    since_90 = now - dt.timedelta(days=90)
    last_90 = sum((overlap_hours(e.started_at, e.ended_at, since_90, now) for e in events), ZERO)
    failures = [e for e in events if e.downtime_type == FAILURE]
    closed_failures = [e for e in failures if e.ended_at]
    mttr_value = (sum((Decimal((e.ended_at - e.started_at).total_seconds()) / 3600 for e in closed_failures), ZERO)
                  / len(closed_failures)) if closed_failures else None
    costs = OperationalExpense.objects.filter(asset=asset, cost_type="ACTUAL")
    year_start = now.date().replace(month=1, day=1)
    by_status = dict(asset.work_orders.values_list("status").annotate(n=Count("id")))
    by_type = dict(asset.work_orders.values_list("maintenance_type").annotate(n=Count("id")))
    cost_by_cat = {k: r2(v) for k, v in costs.values_list("category").annotate(s=Sum("amount"))}
    ongoing = next((e for e in events if e.ended_at is None), None)
    return {
        "downtime_hours_lifetime": r2(lifetime),
        "downtime_hours_90d": r2(last_90),
        "downtime_events": len(events),
        "failures": len(failures),
        "mttr_hours": r2(mttr_value),
        "mttr_status": "ok" if mttr_value is not None else "insufficient_data",
        "ongoing_downtime": ({"id": ongoing.pk, "started_at": ongoing.started_at.isoformat(), "cause": ongoing.cause}
                             if ongoing else None),
        "maintenance_cost_total": r2(costs.aggregate(s=Sum("amount"))["s"] or ZERO),
        "maintenance_cost_ytd": r2(costs.filter(expense_date__gte=year_start).aggregate(s=Sum("amount"))["s"] or ZERO),
        "cost_by_category": cost_by_cat,
        "work_orders_by_status": by_status,
        "work_orders_by_type": by_type,
        "monthly_cost": [{"month": m.isoformat(), "total": r2(s)} for m, s in
                         costs.filter(expense_date__gte=now.date() - dt.timedelta(days=365))
                         .annotate(m=TruncMonth("expense_date")).values_list("m").annotate(s=Sum("amount")).order_by("m")],
    }
