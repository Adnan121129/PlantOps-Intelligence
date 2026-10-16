"""KPI accuracy against a hand-calculated scenario, and reconciliation of the BI views with the app."""
import calendar
import datetime as dt
import zoneinfo
from decimal import Decimal

import pytest
from django.db import connection
from django.utils import timezone

from apps.analytics import services as s
from apps.core.timeutils import Period
from apps.costs.models import Budget, OperationalExpense
from apps.maintenance import services as mnt
from apps.maintenance.models import MaintenanceSchedule, WorkOrder

UTC = zoneinfo.ZoneInfo("UTC")
BASE = (timezone.now() - dt.timedelta(days=60)).date()


def at(day_offset: int, hour: int) -> dt.datetime:
    return dt.datetime.combine(BASE + dt.timedelta(days=day_offset), dt.time(hour), tzinfo=UTC)


@pytest.fixture
def scenario(users, asset, asset2, technician, mnt_dept):
    op, mt = users["OPERATIONS"], users["MAINTENANCE"]
    # A failure that started before the period: only 2 of its 4 hours fall inside.
    mnt.record_downtime(user=op, asset=asset, downtime_type="UNPLANNED_FAILURE", started_at=at(-1, 22), ended_at=at(0, 2),
                        cause="trip")
    wo = mnt.create_work_order(user=op, asset=asset, maintenance_type="CORRECTIVE", title="Trip", description="d",
                               reported_at=at(1, 10))
    mnt.record_downtime(user=op, asset=asset, downtime_type="UNPLANNED_FAILURE", started_at=at(1, 10), ended_at=at(1, 14),
                        cause="trip", work_order=wo)
    mnt.record_downtime(user=mt, asset=asset2, downtime_type="PLANNED_MAINTENANCE", started_at=at(5, 8), ended_at=at(5, 12),
                        cause="PM")
    mnt.assign(wo, user=mt, technician=technician)
    mnt.start(wo, user=mt, actual_start=at(1, 11))
    mnt.add_cost(wo, user=mt, category="LABOR", amount=Decimal("300.00"), description="labour",
                 expense_date=BASE + dt.timedelta(days=1))
    mnt.complete(wo, user=mt, actions_performed="Fixed", failure_code="MECHANICAL", actual_end=at(1, 15))
    mnt.verify(wo, user=users["SUPERVISOR"], approve=True)
    OperationalExpense.objects.create(expense_date=BASE + dt.timedelta(days=2), category="OTHER", amount=Decimal("1000"),
                                      currency="USD", description="Security", recorded_by=users["ADMIN"])
    OperationalExpense.objects.create(expense_date=BASE + dt.timedelta(days=2), category="CONTRACTOR", cost_type="ESTIMATE",
                                      amount=Decimal("99999"), currency="USD", description="Estimate", asset=asset,
                                      recorded_by=users["ADMIN"])
    sched = MaintenanceSchedule.objects.create(asset=asset2, title="PM", interval_days=2, start_date=BASE + dt.timedelta(days=2),
                                               lead_days=1, created_by=mt)
    common = dict(asset=asset2, schedule=sched, maintenance_type="PREVENTIVE", title="PM", description="PM",
                  reported_at=at(0, 6), reported_by=mt)
    WorkOrder.objects.create(number="PM-1", due_date=BASE + dt.timedelta(days=2), status="COMPLETED", actual_start=at(2, 8),
                             actual_end=at(2, 10), **common)                                   # on time
    WorkOrder.objects.create(number="PM-2", due_date=BASE + dt.timedelta(days=4), status="COMPLETED", actual_start=at(6, 8),
                             actual_end=at(6, 10), **common)                                   # late
    WorkOrder.objects.create(number="PM-3", due_date=BASE + dt.timedelta(days=6), status="ASSIGNED", **common)  # missed
    WorkOrder.objects.create(number="PM-4", due_date=BASE + dt.timedelta(days=8), status="CANCELLED",
                             cancelled_reason="Deferred", **common)                            # cancelled counts
    return s.Scope(Period(BASE, BASE + dt.timedelta(days=9), UTC))


@pytest.mark.django_db
def test_downtime_is_clipped_and_not_double_counted(scenario):
    assert s.downtime_hours(scenario) == Decimal(10)          # 2 (clipped) + 4 + 4
    assert s.downtime_hours(scenario, ["UNPLANNED_FAILURE"]) == Decimal(6)
    trend = {r["bucket"]: r["total"] for r in s.downtime_trend(scenario)}
    assert trend[BASE.isoformat()] == 2.0 and trend[(BASE + dt.timedelta(days=1)).isoformat()] == 4.0
    assert sum(trend.values()) == 10.0
    assert s.top_assets_by_downtime(scenario)[0]["hours"] == 6.0


@pytest.mark.django_db
def test_reliability_metrics(scenario):
    assert s.mttr(scenario)["value"] == 4.0          # two failures ended in the period, 4 h each
    mtbf = s.mtbf(scenario)
    assert mtbf["failures"] == 1 and mtbf["status"] == "low_confidence"
    assert mtbf["value"] == 470.0                     # (2 assets x 240 h - 10 h) / 1 failure
    rep = s.repeat_failures(scenario)
    assert rep["failures"] == 1 and rep["repeats"] == 1   # previous failure ~36 h earlier


@pytest.mark.django_db
def test_insufficient_data_is_reported_not_zero(users, asset):
    empty = s.Scope(Period(BASE, BASE + dt.timedelta(days=9), UTC))
    assert s.mttr(empty)["value"] is None and s.mttr(empty)["status"] == "insufficient_data"
    assert s.mtbf(empty)["value"] is None
    assert s.pm_compliance(empty)["value"] is None
    assert s.avg_repair_cost(empty)["value"] is None


@pytest.mark.django_db
def test_pm_compliance_formula(scenario):
    pm = s.pm_compliance(scenario)
    assert (pm["due"], pm["compliant"], pm["completed_late"], pm["not_completed"], pm["cancelled"]) == (4, 1, 1, 1, 1)
    assert pm["value"] == 25.0


@pytest.mark.django_db
def test_costs_use_actuals_and_maintenance_scope(scenario):
    assert s.maintenance_cost(scenario) == Decimal("300.00")
    assert s.operating_cost(scenario) == Decimal("1300.00")       # estimate excluded
    assert s.avg_repair_cost(scenario)["value"] == 300.0
    # 5 WOs reported in period, 1 cancelled (excluded); completed: corrective + PM-1 + PM-2 = 3 of 4
    assert s.wo_completion_rate(scenario)["value"] == 75.0


@pytest.mark.django_db
def test_budget_proration(users):
    first = (timezone.now().date().replace(day=1) - dt.timedelta(days=70)).replace(day=1)
    days = calendar.monthrange(first.year, first.month)[1]
    Budget.objects.create(year=first.year, month=first.month, category="OTHER", amount=Decimal(days * 100), currency="USD")
    scope = s.Scope(Period(first, first + dt.timedelta(days=9), UTC))
    variance = s.budget_variance(scope)
    assert variance["budget"] == 1000.0 and variance["actual"] == 0.0 and variance["value"] == -1000.0


def bi(sql, params=()):
    with connection.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


@pytest.mark.django_db
def test_bi_views_reconcile_with_application_kpis(scenario):
    lo, hi = int(BASE.strftime("%Y%m%d")), int((BASE + dt.timedelta(days=9)).strftime("%Y%m%d"))
    (dt_hours,) = bi("SELECT sum(downtime_hours) FROM bi.fact_downtime_daily WHERE date_key BETWEEN %s AND %s", (lo, hi))
    assert round(float(dt_hours), 4) == float(s.downtime_hours(scenario))
    (maint,) = bi("SELECT sum(amount) FROM bi.fact_operational_costs WHERE cost_type='ACTUAL' AND is_maintenance "
                  "AND date_key BETWEEN %s AND %s", (lo, hi))
    assert maint == s.maintenance_cost(scenario)
    counted, on_time = bi("SELECT count(*) FILTER (WHERE pm_counted), count(*) FILTER (WHERE pm_on_time) "
                          "FROM bi.fact_work_orders WHERE due_date_key BETWEEN %s AND %s", (lo, hi))
    pm = s.pm_compliance(scenario)
    assert (counted, on_time) == (pm["due"], pm["compliant"])
    (n_dates,) = bi("SELECT count(*) FROM bi.dim_date WHERE date_key BETWEEN %s AND %s", (lo, hi))
    assert n_dates == 10
    # the dimension keys used by facts exist (no orphan keys -> no blank rows in Power BI)
    (orphans,) = bi("SELECT count(*) FROM bi.fact_operational_costs f LEFT JOIN bi.dim_asset a ON a.asset_id = f.asset_id "
                    "WHERE a.asset_id IS NULL")
    assert orphans == 0


@pytest.mark.django_db
def test_dashboard_kpis_come_from_records(users, client_for, scenario):
    q = f"date_from={BASE}&date_to={BASE + dt.timedelta(days=9)}"
    data = client_for(users["MANAGEMENT"]).get(f"/api/analytics/dashboard/?{q}").json()
    kpis = {k["code"]: k for k in data["kpis"]}
    assert kpis["downtime_hours"]["value"] == 10.0
    assert kpis["maintenance_cost"]["value"] == 300.0
    assert kpis["pm_compliance_pct"]["value"] == 25.0
    assert kpis["total_assets"]["value"] == 2
    assert kpis["downtime_hours"]["definition"] and kpis["downtime_hours"]["link"].startswith("/maintenance/downtime?")
    # roles without cost access do not receive cost figures
    ops = client_for(users["OPERATIONS"]).get(f"/api/analytics/dashboard/?{q}").json()
    assert "maintenance_cost" not in {k["code"] for k in ops["kpis"]} and ops["restricted"] == ["costs"]
    assert client_for(users["OPERATIONS"]).get("/api/analytics/costs/").status_code == 403


@pytest.mark.django_db
def test_invalid_period_parameters(users, client_for):
    client = client_for(users["MANAGEMENT"])
    assert client.get("/api/analytics/dashboard/?date_from=2026-02-10&date_to=2026-02-01").status_code == 400
    assert client.get("/api/analytics/dashboard/?date_from=bad").status_code == 400


@pytest.mark.django_db
def test_every_documented_dax_measure_reconciles(scenario, metrics):
    from apps.bi.reconcile import reconcile

    checks = reconcile(scenario)
    failed = [(c.measure, c.app_value, c.bi_value) for c in checks if not c.ok]
    assert not failed, failed
    assert {c.measure for c in checks} >= {"Total Downtime Hours", "Total Maintenance Cost", "PM Tasks Due", "MTTR Hours"}
