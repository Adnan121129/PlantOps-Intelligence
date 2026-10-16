"""Whitelisted BI datasets served by the read-only API. Names map 1:1 to views in schema `bi`."""
from __future__ import annotations

DATASETS: dict[str, dict] = {
    "dim_date": {"description": "Calendar dimension 2020-2032 with fiscal year.", "key": "date_key"},
    "dim_plant_unit": {"description": "Plant units with their plant.", "key": "unit_id"},
    "dim_department": {"description": "Departments (-1 = Unassigned).", "key": "department_id"},
    "dim_asset": {"description": "Equipment assets (-1 = No asset).", "key": "asset_id"},
    "dim_employee": {"description": "Employees without contact details or pay rates.", "key": "employee_id"},
    "dim_maintenance_type": {"description": "Maintenance types.", "key": "maintenance_type"},
    "dim_cost_category": {"description": "Cost categories.", "key": "category"},
    "dim_inventory_item": {"description": "Inventory items with current stock and valuation.", "key": "item_id"},
    "dim_supplier": {"description": "Suppliers.", "key": "supplier_id"},
    "dim_metric": {"description": "Operational metric definitions.", "key": "metric_id"},
    "dim_shift": {"description": "Shift definitions.", "key": "shift_id"},
    "fact_operational_measurements": {"description": "Approved operational measurements (report x metric).",
                                      "key": "measurement_id"},
    "fact_work_orders": {"description": "Work orders with timing, overdue and PM-compliance flags.",
                         "key": "work_order_id"},
    "fact_downtime_events": {"description": "Downtime events (whole events).", "key": "event_id"},
    "fact_downtime_daily": {"description": "Downtime split by local calendar day (use for date-sliced totals).",
                            "key": "event_id"},
    "fact_inventory_transactions": {"description": "Stock-ledger movements.", "key": "transaction_id"},
    "fact_operational_costs": {"description": "Cost-ledger rows.", "key": "expense_id"},
    "fact_budget_daily": {"description": "Budgets prorated per day.", "key": "budget_id"},
    "fact_purchase_receipts": {"description": "Goods-receipt lines with value.", "key": "receipt_line_id"},
    "fact_alerts": {"description": "Alerts with status and age.", "key": "alert_id"},
}
