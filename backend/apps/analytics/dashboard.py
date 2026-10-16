"""Assembles dashboard and module-analytics payloads from apps.analytics.services."""
from __future__ import annotations

from decimal import Decimal

from apps.core.settings_registry import get_setting

from . import services as s
from .kpis import kpi


def _status(result: dict) -> str:
    return result.get("status", "ok")


def dashboard(scope: s.Scope, user, granularity: str = "day") -> dict:
    qs = scope.query_string()
    can_cost = user.has_perm_code("costs.view")
    p = scope.period
    assets = s.assets_in_scope(scope).filter(archived_at__isnull=True)
    unavailable = assets.filter(status__in=["OUT_OF_SERVICE", "UNDER_MAINTENANCE"])
    downtime_total = s.downtime_hours(scope)
    unplanned = s.downtime_hours(scope, ["UNPLANNED_FAILURE"])
    pm = s.pm_compliance(scope)
    wo = s.work_order_snapshot(scope)
    stock = s.stock_snapshot()
    incidents = s.open_incidents(scope)
    approvals = s.pending_approvals()
    unit_param = f"&unit={scope.unit.pk}" if scope.unit else ""

    metric = s.primary_metric(scope)
    output = s.metric_aggregate(scope, metric) if metric else {"value": None, "status": "insufficient_data"}

    kpis = [
        kpi("total_assets", assets.count(), link=f"/assets?{unit_param.lstrip('&')}"),
        kpi("assets_unavailable", unavailable.count(), link=f"/assets?out_of_service=true{unit_param}",
            detail={"out_of_service": unavailable.filter(status="OUT_OF_SERVICE").count(),
                    "under_maintenance": unavailable.filter(status="UNDER_MAINTENANCE").count()}),
        kpi("downtime_hours", s.r2(downtime_total), link=f"/maintenance/downtime?{qs}",
            detail={"unplanned_hours": s.r2(unplanned)}),
        kpi("pm_compliance_pct", pm["value"], status=_status(pm), detail=pm,
            link=f"/maintenance/work-orders?preventive=true&due_from={p.date_from}&due_to={p.date_to}{unit_param}"),
        kpi("open_work_orders", wo["open"], detail=wo, link=f"/maintenance/work-orders?open=true{unit_param}"),
        kpi("overdue_work_orders", wo["overdue"], link=f"/maintenance/work-orders?overdue=true{unit_param}",
            status="ok"),
        kpi("low_stock_items", stock["low"], link="/inventory/items?stock_status=LOW",
            detail={"out_of_stock": stock["out_of_stock"]}),
        kpi("critical_stock_items", stock["critical_low"], link="/inventory/items?stock_status=CRITICAL_LOW"),
        kpi("primary_output", output.get("value"), status=_status(output), unit=metric.unit if metric else None,
            detail={**output, "metric": metric.name if metric else None, "metric_id": metric.pk if metric else None},
            link=f"/operations/reports?status=APPROVED&date_from={p.date_from}&date_to={p.date_to}{unit_param}"),
        kpi("open_incidents", incidents["value"], detail=incidents, link=f"/operations/incidents?open=true{unit_param}"),
        kpi("pending_approvals", approvals["value"], detail=approvals["breakdown"], link="/approvals"),
    ]
    currency = get_setting("base_currency")
    if can_cost:
        kpis.insert(6, kpi("maintenance_cost", s.r2(s.maintenance_cost(scope)), unit=currency,
                           link=f"/costs/expenses?maintenance=true&{qs}"))

    charts = {
        "downtime_trend": s.downtime_trend(scope, granularity),
        "failures_by_category": s.failures_by_category(scope),
        "top_downtime_assets": s.top_assets_by_downtime(scope),
        "maintenance_mix": s.maintenance_mix(scope),
        "work_order_status": s.work_order_status_distribution(scope),
        "stock_status": stock["status_counts"],
        "reorder_watchlist": s.reorder_watchlist(),
        "output_trend": s.metric_trend(scope, metric) if metric else [],
        "output_by_shift": s.metric_by_shift(scope, metric) if metric else [],
        "incidents_by_shift": s.incidents_by_shift(scope),
    }
    if can_cost:
        charts["maintenance_cost_by_month"] = s.cost_by_month(scope, maintenance_only=True)
        charts["cost_by_department"] = s.cost_by_department(scope)
    return {
        "period": p.as_dict(),
        "scope": {"plant": scope.plant.pk if scope.plant else None, "plant_name": scope.plant.name if scope.plant else None,
                  "unit": scope.unit.pk if scope.unit else None, "unit_code": scope.unit.code if scope.unit else None},
        "granularity": granularity,
        "currency": currency,
        "output_metric": {"id": metric.pk, "name": metric.name, "unit": metric.unit} if metric else None,
        "kpis": kpis,
        "charts": charts,
        "freshness": s.freshness(),
        "restricted": [] if can_cost else ["costs"],
    }


def maintenance_analytics(scope: s.Scope, granularity: str = "week") -> dict:
    mttr, mtbf = s.mttr(scope), s.mtbf(scope)
    rep, comp, rate, cost = s.repeat_failures(scope), s.pm_compliance(scope), s.wo_completion_rate(scope), s.avg_repair_cost(scope)
    failures = s.failures_in_period(scope).count()
    return {
        "period": scope.period.as_dict(),
        "kpis": [
            kpi("downtime_hours", s.r2(s.downtime_hours(scope))),
            kpi("unplanned_downtime_hours", s.r2(s.downtime_hours(scope, ["UNPLANNED_FAILURE"]))),
            kpi("failure_count", failures),
            kpi("mttr_hours", mttr["value"], status=mttr["status"], detail=mttr),
            kpi("mtbf_hours", mtbf["value"], status=mtbf["status"], detail=mtbf),
            kpi("repeat_failure_pct", rep["value"], status=rep["status"], detail={k: v for k, v in rep.items() if k != "assets"}),
            kpi("pm_compliance_pct", comp["value"], status=comp["status"], detail=comp),
            kpi("wo_completion_rate_pct", rate["value"], status=rate["status"], detail=rate),
            kpi("avg_repair_cost", cost["value"], status=cost["status"], detail=cost, unit=get_setting("base_currency")),
        ],
        "downtime_trend": s.downtime_trend(scope, granularity),
        "top_downtime_assets": s.top_assets_by_downtime(scope, 15),
        "failures_by_category": s.failures_by_category(scope),
        "repeat_failure_assets": rep["assets"],
        "maintenance_mix": s.maintenance_mix(scope),
        "work_order_status": s.work_order_status_distribution(scope),
    }


def inventory_analytics(scope: s.Scope) -> dict:
    stock = s.stock_snapshot()
    turnover = s.inventory_turnover(scope)
    lead = s.supplier_lead_times(scope)
    currency = get_setting("base_currency")
    return {
        "period": scope.period.as_dict(),
        "kpis": [
            kpi("stock_valuation", stock["valuation"], unit=currency),
            kpi("low_stock_items", stock["low"], link="/inventory/items?stock_status=LOW"),
            kpi("critical_stock_items", stock["critical_low"], link="/inventory/items?stock_status=CRITICAL_LOW"),
            kpi("inventory_turnover", turnover["value"], status=turnover["status"], detail=turnover),
            kpi("purchase_spend", s.r2(s.purchase_spend(scope)), unit=currency),
            kpi("open_commitments", s.r2(s.open_commitments()), unit=currency, link="/procurement/orders?open=true"),
            kpi("supplier_lead_time_days", lead["value"], status=lead["status"], detail={"orders": lead["orders"]}),
        ],
        "stock_status": stock["status_counts"],
        "consumption_by_month": s.consumption_by_month(scope),
        "slow_moving": s.slow_moving_items(),
        "slow_moving_days": get_setting("slow_moving_days"),
        "suppliers": lead["suppliers"],
        "reorder_watchlist": s.reorder_watchlist(20),
    }


def cost_analytics(scope: s.Scope) -> dict:
    currency = get_setting("base_currency")
    maint = s.maintenance_cost(scope)
    metric = s.primary_metric(scope)
    output = s.metric_aggregate(scope, metric) if metric else {"value": None}
    per_unit = None
    if metric and metric.aggregation == "SUM" and output.get("value"):
        per_unit = s.r2(maint / Decimal(str(output["value"])))
    variance = s.budget_variance(scope)
    return {
        "period": scope.period.as_dict(),
        "currency": currency,
        "kpis": [
            kpi("operating_cost", s.r2(s.operating_cost(scope)), unit=currency),
            kpi("maintenance_cost", s.r2(maint), unit=currency),
            kpi("budget_variance", variance["value"], status=variance["status"], detail=variance, unit=currency),
            kpi("cost_per_output_unit", per_unit, status="ok" if per_unit is not None else "insufficient_data",
                unit=f"{currency}/{metric.unit}" if metric else None,
                detail={"output": output.get("value"), "metric": metric.name if metric else None}),
        ],
        "by_month": s.cost_by_month(scope),
        "by_category": s.cost_by_category(scope),
        "by_asset": s.cost_by_asset(scope),
        "by_department": s.cost_by_department(scope),
        "by_unit": s.cost_by_unit(scope),
        "anomalies": s.expense_anomalies(),
    }


def operations_analytics(scope: s.Scope, metric_id: int | None = None) -> dict:
    from apps.operations.models import MetricDefinition
    from apps.operations.services import missing_reports

    plant = scope.unit.plant if scope.unit else scope.plant
    metrics = list(MetricDefinition.objects.filter(plant=plant, is_active=True)) if plant else []
    summary = [{"metric_id": m.pk, "code": m.code, "name": m.name, "aggregation": m.aggregation,
                "direction": m.direction, **s.metric_aggregate(scope, m)} for m in metrics]
    selected = next((m for m in metrics if m.pk == metric_id), None) or s.primary_metric(scope) or (metrics[0] if metrics else None)
    gaps = missing_reports(scope.period.date_from, scope.period.date_to,
                           unit_ids=[scope.unit.pk] if scope.unit else None)
    return {
        "period": scope.period.as_dict(),
        "metrics": summary,
        "selected_metric": {"id": selected.pk, "name": selected.name, "unit": selected.unit} if selected else None,
        "trend": s.metric_trend(scope, selected) if selected else [],
        "by_shift": s.metric_by_shift(scope, selected) if selected else [],
        "report_status": s.report_status_counts(scope),
        "missing_reports": len(gaps),
        "incidents_by_shift": s.incidents_by_shift(scope),
    }
