"""Reconciliation of BI-view figures (the SQL behind each documented DAX measure) with application KPIs.

Each check runs the query that a Power BI measure performs over the bi views for a period and
compares it with the value the application computes. Used by `manage.py bi_reconcile` and tests.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.db import connection

from apps.analytics import services as s


@dataclass
class Check:
    measure: str
    app_value: Decimal | float | int | None
    bi_value: Decimal | float | int | None
    tolerance: float = 0.01

    @property
    def ok(self) -> bool:
        if self.app_value is None or self.bi_value is None:
            return self.app_value is None and self.bi_value in (None, 0)
        return abs(float(self.app_value) - float(self.bi_value)) <= self.tolerance


def _one(sql: str, params: list) -> object:
    with connection.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()[0]


def reconcile(scope: s.Scope) -> list[Check]:
    p = scope.period
    lo, hi = int(p.date_from.strftime("%Y%m%d")), int(p.date_to.strftime("%Y%m%d"))
    rng = [lo, hi]
    unit_sql, unit_params = ("", []) if scope.unit is None else (" AND unit_id = %s", [scope.unit.pk])
    pm = s.pm_compliance(scope)
    metric = s.primary_metric(scope)
    out = s.metric_aggregate(scope, metric) if metric else {"value": None, "target": None}
    mttr = s.mttr(scope)
    checks = [
        Check("Total Downtime Hours", s.downtime_hours(scope),
              _one("SELECT COALESCE(sum(downtime_hours),0) FROM bi.fact_downtime_daily WHERE date_key BETWEEN %s AND %s" + unit_sql,
                   rng + unit_params), 0.02),
        Check("Unplanned Downtime Hours", s.downtime_hours(scope, ["UNPLANNED_FAILURE"]),
              _one("SELECT COALESCE(sum(downtime_hours),0) FROM bi.fact_downtime_daily WHERE downtime_type='UNPLANNED_FAILURE' "
                   "AND date_key BETWEEN %s AND %s" + unit_sql, rng + unit_params), 0.02),
        Check("Total Maintenance Cost", s.maintenance_cost(scope),
              _one("SELECT COALESCE(sum(amount),0) FROM bi.fact_operational_costs WHERE cost_type='ACTUAL' AND is_maintenance "
                   "AND date_key BETWEEN %s AND %s" + unit_sql, rng + unit_params)),
        Check("Failure Count", s.failures_in_period(scope).count(),
              _one("SELECT count(*) FROM bi.fact_downtime_events WHERE downtime_type='UNPLANNED_FAILURE' "
                   "AND start_date_key BETWEEN %s AND %s" + unit_sql, rng + unit_params), 0),
        Check("MTTR Hours", mttr["value"],
              _one("SELECT round(avg(duration_hours)::numeric, 2) FROM bi.fact_downtime_events WHERE downtime_type='UNPLANNED_FAILURE' "
                   "AND NOT is_ongoing AND end_date_key BETWEEN %s AND %s" + unit_sql, rng + unit_params)),
        Check("PM Tasks Due", pm["due"],
              _one("SELECT count(*) FROM bi.fact_work_orders WHERE pm_counted AND due_date_key BETWEEN %s AND %s" + unit_sql,
                   rng + unit_params), 0),
        Check("PM Tasks On Time", pm["compliant"],
              _one("SELECT count(*) FROM bi.fact_work_orders WHERE pm_on_time AND due_date_key BETWEEN %s AND %s" + unit_sql,
                   rng + unit_params), 0),
        Check("Open Work Orders", s.work_order_snapshot(scope)["open"],
              _one("SELECT count(*) FROM bi.fact_work_orders WHERE is_open" + unit_sql, unit_params), 0),
        Check("Overdue Work Orders", s.work_order_snapshot(scope)["overdue"],
              _one("SELECT count(*) FROM bi.fact_work_orders WHERE is_overdue" + unit_sql, unit_params), 0),
        Check("Low Stock Item Count", s.stock_snapshot()["low"],
              _one("SELECT count(*) FROM bi.dim_inventory_item WHERE is_active AND stock_status <> 'OK'", []), 0),
        Check("Critical Stock Item Count", s.stock_snapshot()["critical_low"],
              _one("SELECT count(*) FROM bi.dim_inventory_item WHERE is_active AND criticality='CRITICAL' AND stock_status <> 'OK'",
                   []), 0),
    ]
    if scope.unit is None:
        variance = s.budget_variance(scope)
        checks += [
            Check("Total Operating Cost", s.operating_cost(scope),
                  _one("SELECT COALESCE(sum(amount),0) FROM bi.fact_operational_costs WHERE cost_type='ACTUAL' "
                       "AND date_key BETWEEN %s AND %s", rng)),
            Check("Budget Amount", variance["budget"],
                  _one("SELECT round(COALESCE(sum(budget_amount),0)::numeric, 2) FROM bi.fact_budget_daily "
                       "WHERE date_key BETWEEN %s AND %s", rng), 0.05),
        ]
    if metric is not None:
        checks += [
            Check("Energy Output", out["value"],
                  _one("SELECT sum(f.value) FROM bi.fact_operational_measurements f JOIN bi.dim_metric m ON m.metric_id = f.metric_id "
                       "WHERE m.is_primary_output AND f.date_key BETWEEN %s AND %s" + unit_sql.replace("unit_id", "f.unit_id"),
                       rng + unit_params)),
            Check("Output Target", out["target"],
                  _one("SELECT sum(f.target_value) FROM bi.fact_operational_measurements f "
                       "JOIN bi.dim_metric m ON m.metric_id = f.metric_id "
                       "WHERE m.is_primary_output AND f.date_key BETWEEN %s AND %s" + unit_sql.replace("unit_id", "f.unit_id"),
                       rng + unit_params)),
        ]
    return checks
