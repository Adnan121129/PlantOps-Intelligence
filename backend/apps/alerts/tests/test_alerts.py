import datetime as dt
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.alerts import engine
from apps.alerts.models import Alert, AlertRule
from apps.inventory.services import post_transaction
from apps.maintenance import services as mnt


def stock_alerts():
    return Alert.objects.filter(rule__code="CRITICAL_STOCK")


@pytest.mark.django_db
def test_alert_created_deduplicated_and_auto_resolved(users, stocked_item, mnt_dept):
    engine.ensure_rules()
    post_transaction(item_id=stocked_item.pk, txn_type="ISSUE", quantity=9, user=users["STORE"], department=mnt_dept)
    engine.evaluate_rules(["CRITICAL_STOCK"])
    engine.evaluate_rules(["CRITICAL_STOCK"])
    alert = stock_alerts().get()  # evaluated twice, still one alert
    assert alert.status == "OPEN" and alert.occurrence_count == 2
    assert "1 EA in stock" in alert.message and "reorder point of 2" in alert.message
    assert alert.link == f"/inventory/items/{stocked_item.pk}"
    post_transaction(item_id=stocked_item.pk, txn_type="RECEIPT", quantity=10, unit_cost=Decimal("100"),
                     user=users["STORE"], reference="DN")
    engine.evaluate_rules(["CRITICAL_STOCK"])
    alert.refresh_from_db()
    assert alert.status == "RESOLVED" and alert.condition_cleared_at is not None
    assert list(alert.activity.values_list("action", flat=True)) == ["CREATED", "CLEARED"]
    # a recurrence later creates a new alert; history is kept
    post_transaction(item_id=stocked_item.pk, txn_type="ISSUE", quantity=10, user=users["STORE"], department=mnt_dept)
    engine.evaluate_rules(["CRITICAL_STOCK"])
    assert stock_alerts().count() == 2


@pytest.mark.django_db
def test_manual_resolution_reopens_if_condition_persists_dismissed_stays(users, client_for, stocked_item, mnt_dept):
    post_transaction(item_id=stocked_item.pk, txn_type="ISSUE", quantity=9, user=users["STORE"], department=mnt_dept)
    engine.evaluate_rules(["CRITICAL_STOCK"])
    alert = stock_alerts().get()
    client = client_for(users["STORE"])
    assert client.post(f"/api/alerts/alerts/{alert.pk}/acknowledge/").json()["status"] == "ACKNOWLEDGED"
    assert client.post(f"/api/alerts/alerts/{alert.pk}/resolve/", {}, format="json").status_code == 400  # note required
    client.post(f"/api/alerts/alerts/{alert.pk}/resolve/", {"note": "Ordered"}, format="json")
    engine.evaluate_rules(["CRITICAL_STOCK"])
    alert.refresh_from_db()
    assert alert.status == "OPEN"  # still short of stock -> reopened
    client.post(f"/api/alerts/alerts/{alert.pk}/dismiss/", {"note": "Known; supplier delay"}, format="json")
    engine.evaluate_rules(["CRITICAL_STOCK"])
    alert.refresh_from_db()
    assert alert.status == "DISMISSED" and stock_alerts().count() == 1


@pytest.mark.django_db
def test_audience_filtering_and_rule_configuration(users, client_for, stocked_item, mnt_dept):
    post_transaction(item_id=stocked_item.pk, txn_type="ISSUE", quantity=9, user=users["STORE"], department=mnt_dept)
    engine.evaluate_rules(["CRITICAL_STOCK"])
    assert client_for(users["STORE"]).get("/api/alerts/alerts/?active=true").json()["count"] == 1
    assert client_for(users["OPERATIONS"]).get("/api/alerts/alerts/?active=true").json()["count"] == 0
    rule = AlertRule.objects.get(code="EXCESSIVE_DOWNTIME")
    admin = client_for(users["ADMIN"])
    assert admin.patch(f"/api/alerts/rules/{rule.pk}/", {"params": {"bogus": 1}}, format="json").status_code == 400
    assert admin.patch(f"/api/alerts/rules/{rule.pk}/", {"params": {"max_hours": -1}}, format="json").status_code == 400
    r = admin.patch(f"/api/alerts/rules/{rule.pk}/", {"params": {"max_hours": 4}}, format="json")
    assert r.status_code == 200 and r.json()["params"]["max_hours"] == 4 and r.json()["params"]["window_days"] == 7
    assert client_for(users["MAINTENANCE"]).patch(f"/api/alerts/rules/{rule.pk}/", {"is_enabled": False},
                                                   format="json").status_code == 403


@pytest.mark.django_db
def test_downtime_and_overdue_rules(users, asset, technician):
    engine.ensure_rules()
    now = timezone.now()
    mnt.record_downtime(user=users["OPERATIONS"], asset=asset, downtime_type="UNPLANNED_FAILURE",
                        started_at=now - dt.timedelta(hours=10), cause="trip")
    wo = mnt.create_work_order(user=users["MAINTENANCE"], asset=asset, maintenance_type="CORRECTIVE", title="Fix",
                               description="d", reported_at=now - dt.timedelta(hours=10),
                               planned_end=now - dt.timedelta(hours=1))
    summary = engine.evaluate_rules(["EXCESSIVE_DOWNTIME", "WO_OVERDUE"])
    assert summary["EXCESSIVE_DOWNTIME"]["created"] == 1 and summary["WO_OVERDUE"]["created"] == 1
    down = Alert.objects.get(rule__code="EXCESSIVE_DOWNTIME")
    assert down.severity == "CRITICAL"  # high-criticality asset
    assert "exceeding the 8 h limit" in down.message
    assert Alert.objects.get(rule__code="WO_OVERDUE").related_object_id == wo.pk


@pytest.mark.django_db
def test_disabled_rules_do_not_fire(users, stocked_item, mnt_dept):
    engine.ensure_rules()
    AlertRule.objects.filter(code="CRITICAL_STOCK").update(is_enabled=False)
    post_transaction(item_id=stocked_item.pk, txn_type="ISSUE", quantity=9, user=users["STORE"], department=mnt_dept)
    engine.evaluate_rules()
    assert not stock_alerts().exists()


@pytest.mark.django_db
def test_expense_anomaly_is_like_for_like(users):
    """A bill that lands on the same day every month is not a trend; a genuine increase is."""
    from apps.alerts.rules import SPECS, _month_add, eval_expense_anomaly
    from apps.costs.models import OperationalExpense

    now = timezone.now().replace(day=20, hour=12)
    month = now.date().replace(day=1)
    for k in range(0, 5):  # four full months of history before the current month
        m = _month_add(month, -k)
        OperationalExpense.objects.create(expense_date=m.replace(day=5), category="UTILITIES", amount=Decimal("7000"),
                                          currency="USD", description="Monthly water bill", recorded_by=users["ADMIN"])
        OperationalExpense.objects.create(expense_date=m.replace(day=8), category="CONTRACTOR",
                                          amount=Decimal("1000") if k else Decimal("4000"), currency="USD",
                                          description="Contractor services", recorded_by=users["ADMIN"])
    found = {c.dedup_key for c in eval_expense_anomaly(SPECS["EXPENSE_ANOMALY"].defaults, now)}
    assert f"trend:CONTRACTOR:{month:%Y-%m}" in found
    assert f"trend:UTILITIES:{month:%Y-%m}" not in found
