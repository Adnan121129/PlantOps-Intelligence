import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.costs.models import OperationalExpense
from apps.inventory.services import post_transaction
from apps.maintenance import services as mnt
from apps.maintenance.models import DowntimeEvent, MaintenanceSchedule, WorkOrder

NOW = timezone.now


@pytest.fixture
def wo(users, asset):
    return mnt.create_work_order(user=users["OPERATIONS"], asset=asset, maintenance_type="CORRECTIVE",
                                 title="Pump vibration", description="High vibration", priority="HIGH",
                                 reported_at=NOW() - dt.timedelta(hours=10))


@pytest.mark.django_db
def test_corrective_lifecycle_end_to_end(users, client_for, wo, technician, stocked_item, asset):
    maint, sup = client_for(users["MAINTENANCE"]), client_for(users["SUPERVISOR"])
    assert wo.status == "REPORTED" and wo.requires_verification  # high priority -> verification required
    # downtime linked to the work order
    r = client_for(users["OPERATIONS"]).post("/api/maintenance/downtime/", {
        "asset": asset.pk, "work_order": wo.pk, "downtime_type": "UNPLANNED_FAILURE",
        "started_at": (NOW() - dt.timedelta(hours=10)).isoformat(), "cause": "Vibration trip"}, format="json")
    assert r.status_code == 201, r.json()
    event_id = r.json()["id"]
    asset.refresh_from_db()
    assert asset.status == "OUT_OF_SERVICE"

    r = maint.post(f"/api/maintenance/work-orders/{wo.pk}/assign/", {
        "assigned_technician": technician.pk, "planned_end": (NOW() + dt.timedelta(hours=4)).isoformat()}, format="json")
    assert r.json()["status"] == "ASSIGNED"
    r = maint.post(f"/api/maintenance/work-orders/{wo.pk}/start/", {
        "actual_start": (NOW() - dt.timedelta(hours=8)).isoformat()}, format="json")
    assert r.json()["status"] == "IN_PROGRESS"
    r = maint.post(f"/api/maintenance/work-orders/{wo.pk}/issue-part/", {"item": stocked_item.pk, "quantity": 2},
                   format="json")
    assert r.status_code == 201 and r.json()["costs"]["parts"] == 200.0
    r = maint.post(f"/api/maintenance/work-orders/{wo.pk}/costs/", {"category": "LABOR", "amount": "320.00",
                                                                   "description": "8 h"}, format="json")
    assert r.status_code == 201 and r.json()["costs"]["total"] == 520.0
    # cannot complete while the outage is still open
    r = maint.post(f"/api/maintenance/work-orders/{wo.pk}/complete/", {"actions_performed": "Replaced bearing",
                                                                      "failure_code": "MECHANICAL"}, format="json")
    assert r.status_code == 400
    maint.post(f"/api/maintenance/downtime/{event_id}/close/", {"ended_at": (NOW() - dt.timedelta(hours=2)).isoformat()},
               format="json")
    asset.refresh_from_db()
    assert asset.status == "OPERATIONAL"
    r = maint.post(f"/api/maintenance/work-orders/{wo.pk}/complete/", {
        "actions_performed": "Replaced bearing", "failure_code": "MECHANICAL", "labor_hours": "8",
        "actual_end": (NOW() - dt.timedelta(hours=1)).isoformat()}, format="json")
    assert r.json()["status"] == "AWAITING_VERIFICATION"
    # the person who completed it cannot verify it
    assert maint.post(f"/api/maintenance/work-orders/{wo.pk}/verify/", {"decision": "approve"}, format="json").status_code == 400
    r = sup.post(f"/api/maintenance/work-orders/{wo.pk}/verify/", {"decision": "approve"}, format="json")
    assert r.json()["status"] == "COMPLETED"
    assert r.json()["downtime_hours"] == 8.0
    stocked_item.refresh_from_db()
    assert stocked_item.current_stock == 8
    assert OperationalExpense.objects.filter(work_order=wo).count() == 2


@pytest.mark.django_db
def test_invalid_transitions_and_cancellation_rules(users, wo, technician, stocked_item):
    with pytest.raises(ValidationError):
        mnt.start(wo, user=users["MAINTENANCE"])  # not assigned yet
    mnt.assign(wo, user=users["MAINTENANCE"], technician=technician)
    mnt.start(wo, user=users["MAINTENANCE"])
    post_transaction(item_id=stocked_item.pk, txn_type="ISSUE", quantity=1, user=users["STORE"], work_order=wo)
    with pytest.raises(ValidationError):
        mnt.cancel(wo, user=users["MAINTENANCE"], reason="")
    with pytest.raises(ValidationError, match="Return the parts"):
        mnt.cancel(wo, user=users["MAINTENANCE"], reason="Duplicate")
    post_transaction(item_id=stocked_item.pk, txn_type="RETURN", quantity=1, user=users["STORE"], work_order=wo)
    mnt.cancel(wo, user=users["MAINTENANCE"], reason="Duplicate")
    wo.refresh_from_db()
    assert wo.status == "CANCELLED"
    with pytest.raises(ValidationError):
        mnt.assign(wo, user=users["MAINTENANCE"], technician=technician)


@pytest.mark.django_db
def test_fault_reporter_cannot_plan_or_raise_pm(users, asset, technician):
    wo = mnt.create_work_order(user=users["OPERATIONS"], asset=asset, maintenance_type="CORRECTIVE", title="t",
                               description="d", assigned_technician=technician, planned_end=NOW())
    assert wo.status == "REPORTED" and wo.assigned_technician is None and wo.planned_end is None
    with pytest.raises(ValidationError):
        mnt.create_work_order(user=users["OPERATIONS"], asset=asset, maintenance_type="PREVENTIVE", title="t",
                              description="d")


@pytest.mark.django_db
def test_downtime_validation_and_overlap_protection(users, asset, asset2):
    start = NOW() - dt.timedelta(hours=5)
    with pytest.raises(ValidationError):
        mnt.record_downtime(user=users["OPERATIONS"], asset=asset, downtime_type="UNPLANNED_FAILURE", started_at=start,
                            ended_at=start - dt.timedelta(hours=1), cause="x")
    with pytest.raises(ValidationError):
        mnt.record_downtime(user=users["OPERATIONS"], asset=asset, downtime_type="UNPLANNED_FAILURE",
                            started_at=NOW() + dt.timedelta(hours=1), cause="future")
    mnt.record_downtime(user=users["OPERATIONS"], asset=asset, downtime_type="UNPLANNED_FAILURE", started_at=start,
                        ended_at=start + dt.timedelta(hours=2), cause="x")
    with pytest.raises(ValidationError, match="Overlaps"):
        mnt.record_downtime(user=users["OPERATIONS"], asset=asset, downtime_type="UNPLANNED_FAILURE",
                            started_at=start + dt.timedelta(hours=1), cause="y")
    # the same window on another asset is fine
    mnt.record_downtime(user=users["OPERATIONS"], asset=asset2, downtime_type="UNPLANNED_FAILURE", started_at=start,
                        ended_at=start + dt.timedelta(hours=2), cause="x")
    # database exclusion constraint is the backstop even if the service is bypassed
    with pytest.raises(IntegrityError), transaction.atomic():
        DowntimeEvent.objects.create(asset=asset, downtime_type="EXTERNAL", started_at=start + dt.timedelta(minutes=30),
                                     ended_at=start + dt.timedelta(hours=3), cause="bypass", recorded_by=users["ADMIN"])
    # an open-ended event blocks any later event
    mnt.record_downtime(user=users["OPERATIONS"], asset=asset, downtime_type="UNPLANNED_FAILURE",
                        started_at=start + dt.timedelta(hours=3), cause="ongoing")
    with pytest.raises(ValidationError):
        mnt.record_downtime(user=users["OPERATIONS"], asset=asset, downtime_type="UNPLANNED_FAILURE",
                            started_at=start + dt.timedelta(hours=4), cause="again")


@pytest.mark.django_db
def test_downtime_on_closed_work_order_is_locked(users, wo, technician, asset):
    event = mnt.record_downtime(user=users["OPERATIONS"], asset=asset, downtime_type="UNPLANNED_FAILURE",
                                started_at=NOW() - dt.timedelta(hours=9), ended_at=NOW() - dt.timedelta(hours=6),
                                cause="x", work_order=wo)
    mnt.assign(wo, user=users["MAINTENANCE"], technician=technician)
    mnt.start(wo, user=users["MAINTENANCE"], actual_start=NOW() - dt.timedelta(hours=8))
    mnt.complete(wo, user=users["MAINTENANCE"], actions_performed="Fixed", failure_code="ELECTRICAL")
    mnt.verify(wo, user=users["SUPERVISOR"], approve=True)
    with pytest.raises(ValidationError, match="locked"):
        mnt.update_downtime(event, user=users["MAINTENANCE"], data={"ended_at": NOW() - dt.timedelta(hours=1)})


@pytest.mark.django_db
def test_pm_generation_is_idempotent_and_unique(users, asset):
    today = timezone.now().date()
    sched = MaintenanceSchedule.objects.create(asset=asset, title="Lube", interval_days=7, start_date=today + dt.timedelta(days=3),
                                               lead_days=5, created_by=users["MAINTENANCE"])
    created = mnt.generate_pm_work_orders(as_of=today)
    assert [w.due_date for w in created] == [today + dt.timedelta(days=3)]
    assert mnt.generate_pm_work_orders(as_of=today) == []
    # further cycles appear only once they enter the lead window
    assert len(mnt.generate_pm_work_orders(as_of=today + dt.timedelta(days=5))) == 1
    with pytest.raises(IntegrityError), transaction.atomic():
        WorkOrder.objects.create(number="DUP", asset=asset, schedule=sched, maintenance_type="PREVENTIVE", title="x",
                                 description="x", reported_at=NOW(), reported_by=users["MAINTENANCE"],
                                 due_date=today + dt.timedelta(days=3))
    calendar = mnt.pm_calendar(today, today + dt.timedelta(days=30))
    kinds = [(e["date"], e["kind"]) for e in calendar]
    assert ((today + dt.timedelta(days=3)).isoformat(), "work_order") in kinds
    assert ((today + dt.timedelta(days=17)).isoformat(), "projected") in kinds


@pytest.mark.django_db
def test_schedule_api_validations(users, client_for, asset):
    client = client_for(users["MAINTENANCE"])
    old = (timezone.now().date() - dt.timedelta(days=60)).isoformat()
    r = client.post("/api/maintenance/schedules/", {"asset": asset.pk, "title": "X", "interval_days": 30,
                                                    "start_date": old, "lead_days": 5}, format="json")
    assert r.status_code == 400
    r = client.post("/api/maintenance/schedules/", {"asset": asset.pk, "title": "X", "interval_days": 7,
                                                    "start_date": timezone.now().date().isoformat(), "lead_days": 7},
                    format="json")
    assert r.status_code == 400  # lead >= interval
    assert client_for(users["OPERATIONS"]).post("/api/maintenance/schedules/", {}, format="json").status_code == 403


@pytest.mark.django_db
def test_wo_cost_categories_exclude_parts(users, wo):
    with pytest.raises(ValidationError):
        mnt.add_cost(wo, user=users["MAINTENANCE"], category="SPARE_PARTS", amount=Decimal("10"), description="x")
    with pytest.raises(ValidationError):
        mnt.add_cost(wo, user=users["MAINTENANCE"], category="LABOR", amount=Decimal("-5"), description="x")
