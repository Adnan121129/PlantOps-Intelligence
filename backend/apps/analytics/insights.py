"""Rule-based management insights.

Each insight separates three things explicitly:
* observation    - a fact computed from database records, with its evidence values;
* hypothesis     - a possible explanation, labelled as such (may be absent);
* recommendation - a suggested action (may be absent).

No external AI service is called. Every number comes from apps.analytics.services
for the stated period and scope, so the text can be traced back to the KPIs.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from django.db.models import F, Sum

from apps.core.settings_registry import get_setting
from apps.core.timeutils import Period

from . import services as s


def _previous(scope: s.Scope) -> s.Scope:
    p = scope.period
    length = dt.timedelta(days=p.days)
    return s.Scope(Period(p.date_from - length, p.date_from - dt.timedelta(days=1), p.tz), scope.plant, scope.unit)


def _change(cur: Decimal, prev: Decimal) -> float | None:
    return s.pct(cur - prev, prev) if prev else None


def insights(scope: s.Scope, user) -> list[dict]:
    out: list[dict] = []
    p = scope.period
    prev = _previous(scope)
    period_label = f"{p.date_from} to {p.date_to}"
    q = scope.query_string()

    # 1. Downtime contributors
    total = s.downtime_hours(scope)
    prev_total = s.downtime_hours(prev)
    top = s.top_assets_by_downtime(scope, 3)
    if total > 0 and top:
        share = s.pct(sum(Decimal(str(t["hours"])) for t in top), total)
        change = _change(total, prev_total)
        names = ", ".join(f"{t['asset_tag']} ({t['hours']} h)" for t in top)
        out.append({
            "id": "downtime-contributors", "area": "Maintenance", "severity": "attention" if (change or 0) > 20 else "info",
            "title": "Principal contributors to downtime",
            "observation": f"{s.r2(total)} equipment-hours of downtime were recorded in {period_label}. The top "
                           f"{len(top)} assets account for {share}% of it: {names}.",
            "evidence": [{"label": "Total downtime", "value": s.r2(total), "unit": "h"},
                         {"label": "Previous period", "value": s.r2(prev_total), "unit": "h"},
                         {"label": "Change", "value": change, "unit": "%"}],
            "hypothesis": None,
            "recommendation": "Review the work-order history of these assets first; they offer the largest availability gain."
            if share and share >= 50 else None,
            "link": f"/maintenance/downtime?{q}",
        })
    elif total == 0:
        out.append({"id": "downtime-none", "area": "Maintenance", "severity": "info", "title": "No downtime recorded",
                    "observation": f"No downtime events overlap {period_label} in this scope.", "evidence": [],
                    "hypothesis": "If equipment did stop, events may not have been recorded.", "recommendation": None,
                    "link": f"/maintenance/downtime?{q}"})

    # 2. Repeat failures
    rep = s.repeat_failures(scope)
    if rep["repeats"]:
        assets = ", ".join(f"{a['asset_tag']} ({a['repeats']}x)" for a in rep["assets"][:3])
        out.append({
            "id": "repeat-failures", "area": "Maintenance", "severity": "attention",
            "title": "Recurring failures",
            "observation": f"{rep['repeats']} of {rep['failures']} failures ({rep['value']}%) occurred within "
                           f"{rep['window_days']} days of a previous failure on the same asset: {assets}.",
            "evidence": [{"label": "Repeat failures", "value": rep["repeats"], "unit": "failures"},
                         {"label": "All failures", "value": rep["failures"], "unit": "failures"}],
            "hypothesis": "Repeat failures can indicate that the root cause was not removed by the previous repair.",
            "recommendation": "Run a root-cause analysis on the listed assets and check the recorded failure codes.",
            "link": f"/maintenance/downtime?downtime_type=UNPLANNED_FAILURE&{q}",
        })

    # 3. PM compliance
    pm = s.pm_compliance(scope)
    if pm["due"]:
        sev = "critical" if pm["value"] < 70 else "attention" if pm["value"] < 90 else "info"
        out.append({
            "id": "pm-compliance", "area": "Maintenance", "severity": sev, "title": "Preventive-maintenance compliance",
            "observation": f"{pm['compliant']} of {pm['due']} preventive tasks due in the period were completed on time "
                           f"({pm['value']}%). {pm['completed_late']} were late, {pm['not_completed']} are not done and "
                           f"{pm['cancelled']} were cancelled.",
            "evidence": [{"label": "Compliance", "value": pm["value"], "unit": "%"},
                         {"label": "Tasks due", "value": pm["due"], "unit": "tasks"}],
            "hypothesis": None,
            "recommendation": "Prioritise overdue preventive work orders before new routine work." if sev != "info" else None,
            "link": "/maintenance/work-orders?preventive=true&overdue=true",
        })

    # 4. Cost drivers
    if user.has_perm_code("costs.view"):
        maint = s.maintenance_cost(scope)
        prev_maint = s.maintenance_cost(prev)
        top_cost = s.cost_by_asset(scope, 3)
        if maint > 0 and top_cost:
            change = _change(maint, prev_maint)
            names = ", ".join(f"{a['asset_tag']} ({a['total']:,.2f})" for a in top_cost)
            out.append({
                "id": "cost-drivers", "area": "Costs", "severity": "attention" if (change or 0) > 25 else "info",
                "title": "Highest maintenance expenditure",
                "observation": f"Maintenance expenditure was {s.r2(maint):,.2f} {get_setting('base_currency')} "
                               f"({'+' if (change or 0) >= 0 else ''}{change}% vs the previous period). Largest assets: {names}."
                               if change is not None else
                               f"Maintenance expenditure was {s.r2(maint):,.2f}. Largest assets: {names}.",
                "evidence": [{"label": "This period", "value": s.r2(maint), "unit": "currency"},
                             {"label": "Previous period", "value": s.r2(prev_maint), "unit": "currency"}],
                "hypothesis": None, "recommendation": None, "link": f"/costs/analytics?{q}",
            })
        variance = s.budget_variance(scope)
        if variance["status"] == "ok" and variance["variance_pct"] is not None and variance["variance_pct"] > 5:
            out.append({
                "id": "budget-overrun", "area": "Costs", "severity": "attention" if variance["variance_pct"] < 15 else "critical",
                "title": "Spending above budget",
                "observation": f"Actual operating costs of {variance['actual']:,.2f} exceed the prorated budget of "
                               f"{variance['budget']:,.2f} by {variance['variance_pct']}%.",
                "evidence": [{"label": "Variance", "value": variance["value"], "unit": "currency"}],
                "hypothesis": None, "recommendation": "Review the categories with the largest variance.",
                "link": f"/costs/analytics?{q}",
            })

    # 5. Inventory
    from apps.inventory.models import InventoryItem

    critical = []
    for item in InventoryItem.objects.filter(is_active=True, criticality="CRITICAL", current_stock__lte=F("min_stock_level")):
        on_order = item.po_lines.filter(order__status__in=["ISSUED", "PARTIALLY_RECEIVED"]).aggregate(
            q=Sum(F("quantity_ordered") - F("quantity_received")))["q"] or 0
        critical.append((item, on_order))
    uncovered = [i for i, q_ in critical if not q_]
    if critical:
        out.append({
            "id": "critical-spares", "area": "Inventory", "severity": "critical" if uncovered else "attention",
            "title": "Critical spares at or below reorder point",
            "observation": f"{len(critical)} critical spare(s) are at or below their reorder point; "
                           f"{len(uncovered)} have nothing on order"
                           + (f" ({', '.join(i.item_code for i in uncovered[:5])})." if uncovered else "."),
            "evidence": [{"label": "Critical items low", "value": len(critical), "unit": "items"},
                         {"label": "Without open orders", "value": len(uncovered), "unit": "items"}],
            "hypothesis": None,
            "recommendation": "Raise purchase requests for the uncovered items." if uncovered else None,
            "link": "/inventory/items?stock_status=CRITICAL_LOW",
        })

    # 6. Output vs target
    metric = s.primary_metric(scope)
    if metric:
        agg = s.metric_aggregate(scope, metric)
        if agg["status"] == "ok" and agg["vs_target_pct"] is not None:
            gap = agg["vs_target_pct"] - 100
            out.append({
                "id": "output-target", "area": "Operations", "severity": "attention" if gap < -5 else "info",
                "title": f"{metric.name} against target",
                "observation": f"Approved {metric.name.lower()} was {agg['value']:,} {metric.unit} across {agg['reports']} "
                               f"reports, {agg['vs_target_pct']}% of target." + (
                                   f" {agg['missing']} approved report(s) lack a value and are excluded." if agg["missing"] else ""),
                "evidence": [{"label": "Output", "value": agg["value"], "unit": metric.unit},
                             {"label": "Target", "value": agg["target"], "unit": metric.unit}],
                "hypothesis": "Downtime on generating equipment in the same period may explain part of the shortfall."
                if gap < -5 and total > 0 else None,
                "recommendation": None, "link": f"/operations/analytics?{q}",
            })

    # 7. Overdue work
    wo = s.work_order_snapshot(scope)
    if wo["overdue"]:
        out.append({
            "id": "overdue-work", "area": "Maintenance", "severity": "attention",
            "title": "Overdue work orders",
            "observation": f"{wo['overdue']} of {wo['open']} open work orders are overdue; {wo['blocked']} are blocked.",
            "evidence": [{"label": "Overdue", "value": wo["overdue"], "unit": "work orders"}],
            "hypothesis": "Blocked work orders are often waiting for spare parts." if wo["blocked"] else None,
            "recommendation": None, "link": "/maintenance/work-orders?overdue=true",
        })
    order = {"critical": 0, "attention": 1, "info": 2}
    for item in out:
        item["period"] = p.as_dict()
    return sorted(out, key=lambda i: order[i["severity"]])
