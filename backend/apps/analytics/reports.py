"""Report centre: declarative report definitions shared by the JSON, CSV and XLSX outputs.

A report declares its permission, columns and a row generator that receives a Scope
(reporting period + plant/unit) and the requesting user. Rows are plain dicts keyed by
column key. All calculations reuse the analytics services so that reports agree with the
dashboard.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Iterable

from django.db.models import Count, Q, Sum
from django.utils import timezone

from apps.assets.models import EquipmentAsset
from apps.core.timeutils import overlap_hours
from apps.costs.models import OperationalExpense
from apps.inventory.models import InventoryItem, PurchaseOrder, StockTransaction
from apps.maintenance.models import DowntimeEvent, WorkOrder
from apps.operations.models import MetricDefinition, OperationalReport
from apps.workforce.models import OvertimeRecord, ShiftAssignment, ShiftDefinition, ShiftHandover

from . import services as s
from .dashboard import dashboard


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    kind: str = "text"  # text | number | money | date | datetime | percent


@dataclass(frozen=True)
class ReportDef:
    code: str
    title: str
    description: str
    permission: str
    columns: Callable[[s.Scope], list[Column]]
    rows: Callable[[s.Scope, object], Iterable[dict]]
    period_note: str = ""


def _local(value: dt.datetime | None, tz) -> str | None:
    return value.astimezone(tz).strftime("%Y-%m-%d %H:%M") if value else None


def _hours(a, b) -> float | None:
    return round((b - a).total_seconds() / 3600, 2) if a and b else None


# --------------------------------------------------------------------------- operations


def _ops_metrics(scope):
    plant = scope.unit.plant if scope.unit else scope.plant
    return list(MetricDefinition.objects.filter(plant=plant, is_active=True)) if plant else []


def daily_ops_columns(scope):
    return [Column("report_date", "Date", "date"), Column("unit", "Unit"), Column("shift", "Shift"),
            Column("status", "Status"), Column("revision", "Revision", "number")] + [
        Column(f"m_{m.code}", f"{m.name} ({m.unit})", "number") for m in _ops_metrics(scope)] + [
        Column("missing", "Missing values"), Column("incidents", "Incidents", "number"), Column("summary", "Summary")]


def daily_ops_rows(scope, user):
    p = scope.period
    qs = (OperationalReport.objects.filter(scope.unit_q(), report_date__gte=p.date_from, report_date__lte=p.date_to)
          .select_related("plant_unit", "shift").prefetch_related("measurements__metric")
          .annotate(n_inc=Count("incidents")).order_by("report_date", "shift__sequence", "plant_unit__code"))
    if not user.has_perm_code("opsreports.view_all"):
        qs = qs.filter(status="APPROVED")
    for r in qs:
        row = {"report_date": r.report_date.isoformat(), "unit": r.plant_unit.code, "shift": r.shift.name,
               "status": r.status, "revision": r.revision, "incidents": r.n_inc, "summary": r.summary}
        missing = []
        for m in r.measurements.all():
            row[f"m_{m.metric.code}"] = float(m.value) if m.value is not None else None
            if m.value is None:
                missing.append(f"{m.metric.code}: {m.missing_reason}")
        row["missing"] = "; ".join(missing)
        yield row


def handover_rows(scope, user):
    p = scope.period
    for h in (ShiftHandover.objects.filter(scope.unit_q(), date__gte=p.date_from, date__lte=p.date_to)
              .select_related("plant_unit", "shift", "handed_over_by", "received_by").order_by("date", "shift__sequence")):
        yield {"date": h.date.isoformat(), "unit": h.plant_unit.code, "shift": h.shift.name, "summary": h.summary,
               "outstanding": h.outstanding_issues, "safety": h.safety_notes, "by": h.handed_over_by.display_name,
               "received_by": h.received_by.display_name if h.received_by else None,
               "received_at": _local(h.received_at, scope.tz)}


def coverage_rows(scope, user):
    p = scope.period
    counts = {(r["date"], r["shift"]): r["n"] for r in ShiftAssignment.objects.filter(
        date__gte=p.date_from, date__lte=min(p.date_to, p.date_from + dt.timedelta(days=366))).values("date", "shift")
        .annotate(n=Count("id"))}
    shifts = list(ShiftDefinition.objects.filter(is_active=True).order_by("sequence"))
    day = p.date_from
    while day <= p.date_to:
        for sh in shifts:
            n = counts.get((day, sh.pk), 0)
            yield {"date": day.isoformat(), "shift": sh.name, "assigned": n, "min_staff": sh.min_staff,
                   "shortfall": max(sh.min_staff - n, 0),
                   "status": "UNASSIGNED" if n == 0 else "UNDERSTAFFED" if n < sh.min_staff else "COVERED"}
        day += dt.timedelta(days=1)


def overtime_rows(scope, user):
    p = scope.period
    for o in (OvertimeRecord.objects.filter(date__gte=p.date_from, date__lte=p.date_to)
              .select_related("employee__department", "work_order").order_by("date")):
        yield {"date": o.date.isoformat(), "employee": o.employee.employee_code, "name": o.employee.full_name,
               "department": o.employee.department.name, "hours": float(o.hours),
               "multiplier": float(o.rate_multiplier), "cost": float(o.cost) if o.cost is not None else None,
               "status": o.status, "work_order": o.work_order.number if o.work_order else None, "reason": o.reason}


# --------------------------------------------------------------------------- assets & maintenance


def asset_status_rows(scope, user):
    p = scope.period
    events = s.downtime_events(scope)
    hours: dict[int, Decimal] = {}
    for e in events:
        hours[e.asset_id] = hours.get(e.asset_id, Decimal(0)) + overlap_hours(e.started_at, e.ended_at, p.start, p.effective_end)
    from apps.assets.views import annotate_maintenance

    qs = annotate_maintenance(EquipmentAsset.objects.filter(scope.unit_q("plant_unit"), archived_at__isnull=True)
                              .select_related("category", "plant_unit"))
    for a in qs.order_by("plant_unit__code", "asset_tag"):
        yield {"asset_tag": a.asset_tag, "name": a.name, "unit": a.plant_unit.code, "category": a.category.name,
               "criticality": a.criticality, "status": a.status, "open_work_orders": a.open_work_orders,
               "last_maintenance": _local(a.last_maintenance_at, scope.tz),
               "next_due": a.next_maintenance_due.isoformat() if a.next_maintenance_due else None,
               "downtime_hours": s.r2(hours.get(a.pk, Decimal(0)))}


def _wo_cost_map(wo_ids) -> dict[int, Decimal]:
    return dict(OperationalExpense.objects.filter(work_order_id__in=wo_ids, cost_type="ACTUAL")
                .values_list("work_order_id").annotate(t=Sum("amount")))


def _wo_downtime_map(wo_ids) -> dict[int, float]:
    now = timezone.now()
    out: dict[int, float] = {}
    for e in DowntimeEvent.objects.filter(work_order_id__in=wo_ids):
        out[e.work_order_id] = out.get(e.work_order_id, 0) + ((e.ended_at or now) - e.started_at).total_seconds() / 3600
    return {k: round(v, 2) for k, v in out.items()}


def maintenance_history_rows(scope, user):
    p = scope.period
    wos = list(WorkOrder.objects.filter(scope.asset_q(), status="COMPLETED", actual_end__gte=p.start, actual_end__lt=p.end)
               .select_related("asset", "assigned_technician").order_by("actual_end"))
    ids = [w.pk for w in wos]
    costs, downtime = _wo_cost_map(ids), _wo_downtime_map(ids)
    show_cost = user.has_perm_code("costs.view")
    for w in wos:
        yield {"number": w.number, "asset_tag": w.asset.asset_tag, "type": w.maintenance_type, "title": w.title,
               "failure_code": w.failure_code, "root_cause": w.root_cause, "actions": w.actions_performed,
               "technician": w.assigned_technician.full_name if w.assigned_technician else w.assigned_team,
               "started": _local(w.actual_start, scope.tz), "completed": _local(w.actual_end, scope.tz),
               "labor_hours": float(w.labor_hours) if w.labor_hours is not None else None,
               "downtime_hours": downtime.get(w.pk, 0.0),
               "total_cost": s.r2(costs.get(w.pk, Decimal(0))) if show_cost else None}


def downtime_rows(scope, user):
    p = scope.period
    for e in s.downtime_events(scope).select_related("work_order", "asset__plant_unit").order_by("started_at"):
        yield {"asset_tag": e.asset.asset_tag, "asset": e.asset.name, "unit": e.asset.plant_unit.code,
               "category": e.asset.category.name, "type": e.downtime_type, "started": _local(e.started_at, scope.tz),
               "ended": _local(e.ended_at, scope.tz), "ongoing": e.ended_at is None,
               "total_hours": e.duration_hours,
               "hours_in_period": s.r2(overlap_hours(e.started_at, e.ended_at, p.start, p.effective_end)),
               "cause": e.cause, "work_order": e.work_order.number if e.work_order else None}


def pm_rows(scope, user):
    p = scope.period
    from apps.core.settings_registry import get_setting
    from apps.core.timeutils import local_today

    grace = dt.timedelta(days=get_setting("pm_compliance_grace_days"))
    today = local_today(p.tz)
    for w in (WorkOrder.objects.filter(scope.asset_q(), schedule__isnull=False, due_date__gte=p.date_from,
                                       due_date__lte=p.date_to).select_related("asset").order_by("due_date")):
        deadline = w.due_date + grace
        done_date = w.actual_end.astimezone(p.tz).date() if w.actual_end and w.status == "COMPLETED" else None
        if done_date is not None:
            result = "ON_TIME" if done_date <= deadline else "LATE"
        elif w.status == "CANCELLED":
            result = "CANCELLED"
        elif deadline >= today:
            result = "NOT_YET_DUE"
        else:
            result = "MISSED"
        yield {"number": w.number, "asset_tag": w.asset.asset_tag, "task": w.title, "type": w.maintenance_type,
               "due_date": w.due_date.isoformat(), "status": w.status, "completed_on": done_date.isoformat() if done_date else None,
               "days_late": (done_date - w.due_date).days if done_date and done_date > w.due_date else 0, "result": result,
               "counted": result != "NOT_YET_DUE"}


def wo_performance_rows(scope, user):
    wos = list(s.work_orders_reported(scope).select_related("asset", "assigned_technician").order_by("reported_at"))
    ids = [w.pk for w in wos]
    costs, downtime = _wo_cost_map(ids), _wo_downtime_map(ids)
    now, today = timezone.now(), timezone.localdate()
    from apps.core.settings_registry import get_setting
    from apps.maintenance.serializers import is_overdue

    grace = get_setting("pm_compliance_grace_days")
    show_cost = user.has_perm_code("costs.view")
    for w in wos:
        yield {"number": w.number, "asset_tag": w.asset.asset_tag, "type": w.maintenance_type, "priority": w.priority,
               "status": w.status, "reported": _local(w.reported_at, scope.tz),
               "response_hours": _hours(w.reported_at, w.actual_start), "repair_hours": _hours(w.actual_start, w.actual_end),
               "overdue": is_overdue(w, now=now, today=today, grace=grace), "blocked": w.is_blocked,
               "downtime_hours": downtime.get(w.pk, 0.0),
               "total_cost": s.r2(costs.get(w.pk, Decimal(0))) if show_cost else None}


# --------------------------------------------------------------------------- inventory & procurement


def stock_movement_rows(scope, user):
    p = scope.period
    for t in (StockTransaction.objects.filter(occurred_at__gte=p.start, occurred_at__lt=p.end)
              .select_related("item", "work_order", "department", "recorded_by").order_by("occurred_at", "id").iterator()):
        yield {"txn_number": t.txn_number, "occurred": _local(t.occurred_at, scope.tz), "item_code": t.item.item_code,
               "item": t.item.name, "type": t.txn_type, "quantity": float(t.quantity), "uom": t.item.uom,
               "unit_cost": float(t.unit_cost), "value": float(t.total_value), "balance_after": float(t.balance_after),
               "work_order": t.work_order.number if t.work_order else None,
               "department": t.department.name if t.department else None, "reference": t.reference,
               "recorded_by": t.recorded_by.display_name, "notes": t.notes}


def inventory_status_rows(scope, user):
    for i in InventoryItem.objects.filter(is_active=True).select_related("category", "preferred_supplier").order_by("item_code"):
        yield {"item_code": i.item_code, "name": i.name, "category": i.category.name, "criticality": i.criticality,
               "stock": float(i.current_stock), "uom": i.uom, "min_stock": float(i.min_stock_level),
               "reorder_qty": float(i.reorder_quantity), "unit_cost": float(i.unit_cost),
               "value": s.r2(i.current_stock * i.unit_cost), "status": i.stock_status, "location": i.storage_location,
               "supplier": i.preferred_supplier.name if i.preferred_supplier else None,
               "last_movement": _local(i.last_movement_at, scope.tz)}


def procurement_rows(scope, user):
    p = scope.period
    qs = (PurchaseOrder.objects.filter(Q(order_date__gte=p.date_from, order_date__lte=p.date_to) |
                                       Q(order_date__isnull=True, created_at__gte=p.start, created_at__lt=p.end))
          .select_related("supplier", "purchase_request").prefetch_related("lines").order_by("created_at"))
    for po in qs:
        lines = list(po.lines.all())
        ordered = sum((l.quantity_ordered * l.unit_price for l in lines), Decimal(0))
        received = sum((l.quantity_received * l.unit_price for l in lines), Decimal(0))
        lead = (po.fully_received_at.astimezone(p.tz).date() - po.order_date).days if po.fully_received_at and po.order_date else None
        yield {"po_number": po.po_number, "pr_number": po.purchase_request.pr_number if po.purchase_request else None,
               "supplier": po.supplier.name, "status": po.status,
               "order_date": po.order_date.isoformat() if po.order_date else None,
               "expected": po.expected_delivery_date.isoformat() if po.expected_delivery_date else None,
               "ordered_value": s.r2(ordered), "received_value": s.r2(received),
               "outstanding_value": s.r2(ordered - received) if po.status in ("ISSUED", "PARTIALLY_RECEIVED") else 0.0,
               "lead_time_days": lead,
               "on_time": (lead is not None and po.expected_delivery_date is not None and
                           po.fully_received_at.astimezone(p.tz).date() <= po.expected_delivery_date) if lead is not None else None}


def cost_rows(scope, user):
    for e in (s.actual_expenses(scope).select_related("asset", "work_order", "department", "plant_unit")
              .order_by("expense_date", "id").iterator()):
        yield {"date": e.expense_date.isoformat(), "category": e.category, "amount": float(e.amount), "currency": e.currency,
               "description": e.description, "asset_tag": e.asset.asset_tag if e.asset else None,
               "work_order": e.work_order.number if e.work_order else None,
               "department": e.department.name if e.department else None,
               "unit": e.plant_unit.code if e.plant_unit else None, "source": e.source, "reference": e.reference}


def executive_rows(scope, user):
    data = dashboard(scope, user)
    from .dashboard import maintenance_analytics

    seen = set()
    for k in data["kpis"] + maintenance_analytics(scope)["kpis"]:
        if k["code"] in seen:
            continue
        seen.add(k["code"])
        yield {"code": k["code"], "kpi": k["label"], "value": k["value"], "unit": k["unit"], "status": k["status"],
               "period_type": k["period_type"], "definition": k["definition"]}


def static(*cols: tuple) -> Callable[[s.Scope], list[Column]]:
    columns = [Column(*c) for c in cols]
    return lambda scope: columns


REPORTS: dict[str, ReportDef] = {r.code: r for r in [
    ReportDef("daily_operations", "Daily operations report", "Shift reports with all metric values in the period. "
              "Users without full access see approved reports only.", "reports.view", daily_ops_columns, daily_ops_rows),
    ReportDef("shift_handover", "Shift handover report", "Handover notes and acknowledgements.", "employees.view",
              static(("date", "Date", "date"), ("unit", "Unit"), ("shift", "Shift"), ("summary", "Summary"),
                     ("outstanding", "Outstanding issues"), ("safety", "Safety notes"), ("by", "Handed over by"),
                     ("received_by", "Received by"), ("received_at", "Received at", "datetime")), handover_rows),
    ReportDef("staffing_coverage", "Staffing coverage", "Assigned headcount versus minimum staffing per shift.",
              "employees.view", static(("date", "Date", "date"), ("shift", "Shift"), ("assigned", "Assigned", "number"),
                                       ("min_staff", "Minimum", "number"), ("shortfall", "Shortfall", "number"),
                                       ("status", "Status")), coverage_rows),
    ReportDef("overtime", "Overtime report", "Overtime hours and approved cost.", "overtime.view",
              static(("date", "Date", "date"), ("employee", "Employee code"), ("name", "Name"), ("department", "Department"),
                     ("hours", "Hours", "number"), ("multiplier", "Multiplier", "number"), ("cost", "Cost", "money"),
                     ("status", "Status"), ("work_order", "Work order"), ("reason", "Reason")), overtime_rows),
    ReportDef("asset_status", "Asset status report", "Current status of every registered asset, with downtime in the period.",
              "assets.view", static(("asset_tag", "Asset"), ("name", "Name"), ("unit", "Unit"), ("category", "Category"),
                                    ("criticality", "Criticality"), ("status", "Status"),
                                    ("open_work_orders", "Open WOs", "number"),
                                    ("last_maintenance", "Last maintenance", "datetime"), ("next_due", "Next PM due", "date"),
                                    ("downtime_hours", "Downtime in period (h)", "number")), asset_status_rows),
    ReportDef("maintenance_history", "Maintenance history", "Work orders completed in the period with actions and costs.",
              "workorders.view", static(("number", "Work order"), ("asset_tag", "Asset"), ("type", "Type"), ("title", "Title"),
                                        ("failure_code", "Failure code"), ("root_cause", "Root cause"),
                                        ("actions", "Actions performed"), ("technician", "Technician"),
                                        ("started", "Started", "datetime"), ("completed", "Completed", "datetime"),
                                        ("labor_hours", "Labour h", "number"), ("downtime_hours", "Downtime h", "number"),
                                        ("total_cost", "Total cost", "money")), maintenance_history_rows),
    ReportDef("downtime_analysis", "Downtime analysis", "Downtime events overlapping the period; hours are clipped to "
              "the period.", "assets.view",
              static(("asset_tag", "Asset"), ("asset", "Name"), ("unit", "Unit"), ("category", "Category"), ("type", "Type"),
                     ("started", "Started", "datetime"), ("ended", "Ended", "datetime"), ("ongoing", "Ongoing"),
                     ("total_hours", "Event duration (h)", "number"), ("hours_in_period", "Hours in period", "number"),
                     ("cause", "Cause"), ("work_order", "Work order")), downtime_rows),
    ReportDef("pm_compliance", "Preventive-maintenance compliance", "Each scheduled task due in the period and whether it "
              "counted as on time. Rows marked NOT_YET_DUE are excluded from the KPI.", "workorders.view",
              static(("number", "Work order"), ("asset_tag", "Asset"), ("task", "Task"), ("type", "Type"),
                     ("due_date", "Due", "date"), ("status", "Status"), ("completed_on", "Completed", "date"),
                     ("days_late", "Days late", "number"), ("result", "Result"), ("counted", "Counted in KPI")), pm_rows),
    ReportDef("work_order_performance", "Work-order performance", "Work orders reported in the period with response "
              "and repair times.", "workorders.view",
              static(("number", "Work order"), ("asset_tag", "Asset"), ("type", "Type"), ("priority", "Priority"),
                     ("status", "Status"), ("reported", "Reported", "datetime"), ("response_hours", "Response (h)", "number"),
                     ("repair_hours", "Repair (h)", "number"), ("overdue", "Overdue"), ("blocked", "Blocked"),
                     ("downtime_hours", "Downtime (h)", "number"), ("total_cost", "Cost", "money")), wo_performance_rows),
    ReportDef("stock_movements", "Inventory and stock movements", "The stock ledger for the period.", "inventory.view",
              static(("txn_number", "Txn"), ("occurred", "Date", "datetime"), ("item_code", "Item"), ("item", "Name"),
                     ("type", "Type"), ("quantity", "Quantity", "number"), ("uom", "UoM"), ("unit_cost", "Unit cost", "money"),
                     ("value", "Value", "money"), ("balance_after", "Balance", "number"), ("work_order", "Work order"),
                     ("department", "Department"), ("reference", "Reference"), ("recorded_by", "Recorded by"),
                     ("notes", "Notes")), stock_movement_rows),
    ReportDef("inventory_status", "Inventory status", "Stock on hand, valuation and reorder status (snapshot).",
              "inventory.view",
              static(("item_code", "Item"), ("name", "Name"), ("category", "Category"), ("criticality", "Criticality"),
                     ("stock", "Stock", "number"), ("uom", "UoM"), ("min_stock", "Reorder point", "number"),
                     ("reorder_qty", "Reorder qty", "number"), ("unit_cost", "Unit cost", "money"), ("value", "Value", "money"),
                     ("status", "Status"), ("location", "Location"), ("supplier", "Supplier"),
                     ("last_movement", "Last movement", "datetime")), inventory_status_rows),
    ReportDef("procurement", "Procurement report", "Purchase orders placed in the period with receipt status and lead time.",
              "procurement.view",
              static(("po_number", "PO"), ("pr_number", "PR"), ("supplier", "Supplier"), ("status", "Status"),
                     ("order_date", "Ordered", "date"), ("expected", "Expected", "date"),
                     ("ordered_value", "Ordered value", "money"), ("received_value", "Received value", "money"),
                     ("outstanding_value", "Outstanding", "money"), ("lead_time_days", "Lead time (days)", "number"),
                     ("on_time", "On time")), procurement_rows),
    ReportDef("maintenance_cost", "Cost report", "All actual cost-ledger entries dated in the period.", "costs.view",
              static(("date", "Date", "date"), ("category", "Category"), ("amount", "Amount", "money"),
                     ("currency", "Currency"), ("description", "Description"), ("asset_tag", "Asset"),
                     ("work_order", "Work order"), ("department", "Department"), ("unit", "Unit"), ("source", "Source"),
                     ("reference", "Reference")), cost_rows),
    ReportDef("executive_kpi_summary", "Executive KPI summary", "Headline KPIs for the period with their definitions.",
              "dashboard.view",
              static(("code", "Code"), ("kpi", "KPI"), ("value", "Value", "number"), ("unit", "Unit"), ("status", "Status"),
                     ("period_type", "Period type"), ("definition", "Definition")), executive_rows),
]}
