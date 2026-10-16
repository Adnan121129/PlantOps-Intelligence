"""KPI dictionary: the single definition of every metric shown in the application.

The dashboard API attaches these definitions to each value, and
`manage.py export_kpi_dictionary` renders them to docs/KPI_DICTIONARY.md, so the
documentation cannot drift from the implementation.

Period conventions (apply to all "period" KPIs):
* A reporting period is an inclusive range of local dates in the plant's time zone,
  evaluated as the half-open interval [00:00 of date_from, 00:00 of date_to + 1 day).
* Periods that include today are clipped at the current time ("elapsed period").
* "Snapshot" KPIs describe the current state and ignore the date range.
"""
from __future__ import annotations

KPIS: dict[str, dict] = {
    "total_assets": {
        "label": "Registered assets", "unit": "assets", "period": "snapshot",
        "definition": "Equipment assets in the register that are not archived (retired).",
        "formula": "COUNT(asset) WHERE archived_at IS NULL",
        "source": "assets.EquipmentAsset",
    },
    "assets_unavailable": {
        "label": "Equipment out of service", "unit": "assets", "period": "snapshot",
        "definition": "Non-archived assets whose current status is Out of Service or Under Maintenance.",
        "formula": "COUNT(asset) WHERE status IN (OUT_OF_SERVICE, UNDER_MAINTENANCE)",
        "source": "assets.EquipmentAsset (status is synchronised from open downtime events)",
    },
    "downtime_hours": {
        "label": "Total downtime", "unit": "h", "period": "period",
        "definition": "Equipment-hours of downtime falling inside the period, summed over assets. Events crossing the "
                      "period boundary are clipped; ongoing events count up to now.",
        "formula": "SUM over events of overlap([started_at, COALESCE(ended_at, now)), period)",
        "source": "maintenance.DowntimeEvent (source of truth for downtime; never typed as a duration)",
        "notes": "Overlapping events on one asset are rejected, so no hour is counted twice for an asset. Hours on "
                 "different assets add up (5 h on two assets = 10 equipment-hours).",
    },
    "unplanned_downtime_hours": {
        "label": "Unplanned downtime", "unit": "h", "period": "period",
        "definition": "Downtime hours from events of type 'Unplanned - equipment failure'.",
        "formula": "downtime_hours WHERE downtime_type = UNPLANNED_FAILURE",
        "source": "maintenance.DowntimeEvent",
    },
    "pm_compliance_pct": {
        "label": "PM compliance", "unit": "%", "period": "period",
        "definition": "Share of preventive/inspection tasks due in the period that were completed on or before their "
                      "due date plus the configured grace days. A task enters the denominator once its compliance "
                      "deadline has passed, or earlier if it is already completed.",
        "formula": "100 x COUNT(PM WO due in period, COMPLETED, completion local date <= due_date + grace) / "
                   "COUNT(PM WO due in period WHERE due_date + grace < today OR status = COMPLETED)",
        "source": "maintenance.WorkOrder with schedule IS NOT NULL",
        "notes": "Cancelled tasks stay in the denominator (counted as not compliant) so cancelling cannot inflate "
                 "compliance. Not reported when no task was due.",
    },
    "open_work_orders": {
        "label": "Open work orders", "unit": "work orders", "period": "snapshot",
        "definition": "Work orders in Reported, Assigned, In progress or Awaiting verification.",
        "formula": "COUNT(WO) WHERE status IN open statuses",
        "source": "maintenance.WorkOrder",
    },
    "overdue_work_orders": {
        "label": "Overdue work orders", "unit": "work orders", "period": "snapshot",
        "definition": "Open corrective work orders past their planned completion time, plus open preventive tasks "
                      "past due date + grace days.",
        "formula": "COUNT(open WO WHERE (schedule IS NULL AND planned_end < now) OR (schedule IS NOT NULL AND "
                   "due_date + grace < today))",
        "source": "maintenance.WorkOrder",
        "notes": "Corrective work orders without a planned completion time cannot be overdue.",
    },
    "maintenance_cost": {
        "label": "Maintenance expenditure", "unit": "currency", "period": "period",
        "definition": "Actual costs dated in the period that are linked to a work order or an asset (parts issued, "
                      "labour, contractors, repairs).",
        "formula": "SUM(expense.amount) WHERE cost_type = ACTUAL AND (work_order IS NOT NULL OR asset IS NOT NULL)",
        "source": "costs.OperationalExpense (single cost ledger)",
        "notes": "Parts are costed when issued, not when purchased, so purchases are never counted twice. Returns "
                 "post negative credits.",
    },
    "operating_cost": {
        "label": "Total operating expenditure", "unit": "currency", "period": "period",
        "definition": "All actual costs dated in the period.",
        "formula": "SUM(expense.amount) WHERE cost_type = ACTUAL",
        "source": "costs.OperationalExpense",
    },
    "low_stock_items": {
        "label": "Low-stock items", "unit": "items", "period": "snapshot",
        "definition": "Active inventory items whose stock on hand is at or below the reorder point (all criticalities).",
        "formula": "COUNT(item) WHERE active AND current_stock <= min_stock_level",
        "source": "inventory.InventoryItem",
    },
    "critical_stock_items": {
        "label": "Critical spares low", "unit": "items", "period": "snapshot",
        "definition": "The subset of low-stock items classified as critical spares.",
        "formula": "low_stock_items WHERE criticality = CRITICAL",
        "source": "inventory.InventoryItem",
    },
    "primary_output": {
        "label": "Approved output", "unit": "metric unit", "period": "period",
        "definition": "Sum (or average, per the metric's aggregation) of the plant's primary output metric on "
                      "APPROVED reports dated in the period.",
        "formula": "SUM(measurement.value) WHERE metric.is_primary_output AND report.status = APPROVED",
        "source": "operations.OperationalMeasurement",
        "notes": "Missing values are excluded, never treated as zero; the number of reports lacking a value is shown.",
    },
    "output_vs_target_pct": {
        "label": "Output vs target", "unit": "%", "period": "period",
        "definition": "Approved primary output as a percentage of the target for the same approved reports.",
        "formula": "100 x SUM(value) / (COUNT(reports with a value) x metric.target_value)",
        "source": "operations.OperationalMeasurement, operations.MetricDefinition",
        "notes": "Not reported when the metric has no target.",
    },
    "open_incidents": {
        "label": "Open incidents", "unit": "incidents", "period": "snapshot",
        "definition": "Operational incidents that are Open or Under investigation.",
        "formula": "COUNT(incident) WHERE status != RESOLVED",
        "source": "operations.OperationalIncident",
    },
    "pending_approvals": {
        "label": "Pending approvals", "unit": "items", "period": "snapshot",
        "definition": "Items waiting for a decision: submitted operational reports, submitted purchase requests, work "
                      "orders awaiting verification and pending overtime records.",
        "formula": "COUNT(reports SUBMITTED) + COUNT(PR SUBMITTED) + COUNT(WO AWAITING_VERIFICATION) + "
                   "COUNT(overtime PENDING)",
        "source": "operations, inventory, maintenance, workforce",
    },
    "mttr_hours": {
        "label": "MTTR", "unit": "h", "period": "period",
        "definition": "Mean Time To Repair: average duration of closed unplanned-failure downtime events that ended "
                      "in the period.",
        "formula": "AVG(ended_at - started_at) WHERE downtime_type = UNPLANNED_FAILURE AND ended_at IN period",
        "source": "maintenance.DowntimeEvent",
        "notes": "Not reported without at least one closed failure event. Measures restoration time (failure to "
                 "return to service), including waiting time.",
    },
    "mtbf_hours": {
        "label": "MTBF", "unit": "h", "period": "period",
        "definition": "Mean Time Between Failures: equipment uptime in the period divided by the number of failures "
                      "that started in the period.",
        "formula": "(assets_in_scope x elapsed period hours - downtime_hours) / COUNT(failure events started in period)",
        "source": "maintenance.DowntimeEvent, assets.EquipmentAsset",
        "notes": "Not reported when there were no failures. Flagged as low-confidence below 3 failures. Assets "
                 "commissioned or archived mid-period are counted for the whole period (approximation).",
    },
    "failure_count": {
        "label": "Breakdowns", "unit": "failures", "period": "period",
        "definition": "Unplanned-failure downtime events that started in the period.",
        "formula": "COUNT(event) WHERE downtime_type = UNPLANNED_FAILURE AND started_at IN period",
        "source": "maintenance.DowntimeEvent",
    },
    "repeat_failure_pct": {
        "label": "Repeat failures", "unit": "%", "period": "period",
        "definition": "Share of failures in the period that occurred on an asset within the repeat-failure window "
                      "(setting) of that asset's previous failure.",
        "formula": "100 x COUNT(failures with previous failure on same asset within N days) / failure_count",
        "source": "maintenance.DowntimeEvent",
    },
    "wo_completion_rate_pct": {
        "label": "Work-order completion rate", "unit": "%", "period": "period",
        "definition": "Of the work orders reported in the period and not cancelled, the share completed so far.",
        "formula": "100 x COUNT(WO reported in period, COMPLETED) / COUNT(WO reported in period, status != CANCELLED)",
        "source": "maintenance.WorkOrder",
    },
    "avg_repair_cost": {
        "label": "Average repair cost", "unit": "currency", "period": "period",
        "definition": "Average total actual cost (all dates) of corrective work orders completed in the period.",
        "formula": "SUM(actual expenses of those WOs) / COUNT(corrective WOs with actual_end in period, COMPLETED)",
        "source": "maintenance.WorkOrder, costs.OperationalExpense",
        "notes": "Not reported when no corrective work order was completed.",
    },
    "stock_valuation": {
        "label": "Stock valuation", "unit": "currency", "period": "snapshot",
        "definition": "Value of stock on hand at weighted-average cost.",
        "formula": "SUM(current_stock x unit_cost) over active items",
        "source": "inventory.InventoryItem",
    },
    "inventory_turnover": {
        "label": "Stock turnover (annualised)", "unit": "turns/yr", "period": "period",
        "definition": "Net value issued in the period divided by the average of opening and closing stock value, "
                      "scaled to a year.",
        "formula": "(net issue value / ((value at start + value at end) / 2)) x 365 / period days",
        "source": "inventory.StockTransaction (stock value at a time = cumulative ledger value)",
        "notes": "Not reported for periods under 28 days or when average stock value is zero.",
    },
    "purchase_spend": {
        "label": "Goods received value", "unit": "currency", "period": "period",
        "definition": "Value of goods received against purchase orders in the period (quantity x order price).",
        "formula": "SUM(receipt_line.quantity x po_line.unit_price) WHERE received_at IN period",
        "source": "inventory.GoodsReceiptLine",
        "notes": "This is inventory acquisition, not maintenance expense. Open-order value is a commitment.",
    },
    "open_commitments": {
        "label": "Open purchase commitments", "unit": "currency", "period": "snapshot",
        "definition": "Value of quantities ordered but not yet received on issued purchase orders.",
        "formula": "SUM((qty_ordered - qty_received) x unit_price) WHERE PO status IN (ISSUED, PARTIALLY_RECEIVED)",
        "source": "inventory.PurchaseOrderLine",
    },
    "supplier_lead_time_days": {
        "label": "Average supplier lead time", "unit": "days", "period": "period",
        "definition": "Average days from order date to full receipt for purchase orders fully received in the period.",
        "formula": "AVG(local date(fully_received_at) - order_date)",
        "source": "inventory.PurchaseOrder",
        "notes": "Not reported when no order was fully received in the period.",
    },
    "cost_per_output_unit": {
        "label": "Maintenance cost per output unit", "unit": "currency / output unit", "period": "period",
        "definition": "Maintenance expenditure divided by approved primary output in the same period and scope.",
        "formula": "maintenance_cost / primary_output",
        "source": "costs.OperationalExpense, operations.OperationalMeasurement",
        "notes": "Not reported when output is missing or zero.",
    },
    "budget_variance": {
        "label": "Actual vs budget", "unit": "currency", "period": "period",
        "definition": "Actual costs minus budget for the period. Monthly budgets are prorated by the number of period "
                      "days that fall in each month.",
        "formula": "SUM(actual) - SUM(budget.amount x days_in_period_and_month / days_in_month)",
        "source": "costs.OperationalExpense, costs.Budget",
        "notes": "Positive variance = overspend.",
    },
}


def kpi(code: str, value, *, status: str = "ok", detail: dict | None = None, link: str | None = None,
        unit: str | None = None) -> dict:
    meta = KPIS[code]
    return {
        "code": code,
        "label": meta["label"],
        "value": value,
        "unit": unit or meta["unit"],
        "period_type": meta["period"],
        "definition": meta["definition"],
        "formula": meta["formula"],
        "notes": meta.get("notes", ""),
        "status": status,
        "detail": detail or {},
        "link": link,
    }
