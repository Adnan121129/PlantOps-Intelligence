import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.accounts.models import ApprovalRecord
from apps.operations import services as ops
from apps.operations.models import OperationalReport

YESTERDAY = timezone.now().date() - dt.timedelta(days=1)


def payload(unit, shift, metrics, energy="900", avail="97.5", day=YESTERDAY):
    return {"plant_unit": unit.pk, "shift": shift.pk, "report_date": day.isoformat(), "summary": "Normal",
            "measurements": [{"metric": metrics["energy"].pk, "value": energy},
                             {"metric": metrics["avail"].pk, "value": avail}]}


@pytest.fixture
def ops_client(users, client_for):
    return client_for(users["OPERATIONS"])


@pytest.mark.django_db
def test_full_report_workflow_with_rejection_and_reopen(users, client_for, ops_client, unit, shifts, metrics):
    r = ops_client.post("/api/operations/reports/", payload(unit, shifts[0], metrics), format="json")
    assert r.status_code == 201, r.json()
    rid = r.json()["id"]
    assert r.json()["status"] == "DRAFT"
    assert ops_client.post(f"/api/operations/reports/{rid}/submit/").json()["status"] == "SUBMITTED"
    # Submitted reports are locked for the author
    assert ops_client.patch(f"/api/operations/reports/{rid}/", {"summary": "x"}, format="json").status_code == 400

    sup = client_for(users["SUPERVISOR"])
    r = sup.post(f"/api/operations/reports/{rid}/review/", {"decision": "reject"}, format="json")
    assert r.status_code == 400  # comment required
    r = sup.post(f"/api/operations/reports/{rid}/review/", {"decision": "reject", "comment": "Check meter"}, format="json")
    assert r.json()["status"] == "REJECTED"
    r = ops_client.patch(f"/api/operations/reports/{rid}/", {"measurements": [
        {"metric": metrics["energy"].pk, "value": "905"}, {"metric": metrics["avail"].pk, "value": "97.5"}]}, format="json")
    assert r.status_code == 200
    ops_client.post(f"/api/operations/reports/{rid}/submit/")
    r = sup.post(f"/api/operations/reports/{rid}/review/", {"decision": "approve"}, format="json")
    assert r.json()["status"] == "APPROVED"
    # Approved reports cannot be silently overwritten
    assert ops_client.patch(f"/api/operations/reports/{rid}/", {"summary": "edit"}, format="json").status_code == 400
    # An authorised, audited reopen creates a new revision and keeps the approved values in history
    assert sup.post(f"/api/operations/reports/{rid}/reopen/", {}, format="json").status_code == 400
    r = sup.post(f"/api/operations/reports/{rid}/reopen/", {"reason": "Meter recalibrated"}, format="json")
    assert r.json()["status"] == "DRAFT" and r.json()["revision"] == 2
    actions = list(ApprovalRecord.objects.filter(object_id=rid).values_list("action", flat=True))
    assert actions == ["SUBMIT", "REJECT", "SUBMIT", "APPROVE", "REOPEN"]
    reopen = ApprovalRecord.objects.get(object_id=rid, action="REOPEN")
    assert reopen.snapshot["metric:ENERGY"] == "905.0000"


@pytest.mark.django_db
def test_duplicate_report_for_same_scope_is_rejected(ops_client, unit, shifts, metrics):
    assert ops_client.post("/api/operations/reports/", payload(unit, shifts[0], metrics), format="json").status_code == 201
    r = ops_client.post("/api/operations/reports/", payload(unit, shifts[0], metrics), format="json")
    assert r.status_code == 400 and "already exists" in str(r.json())
    # Another shift on the same day is a different scope
    assert ops_client.post("/api/operations/reports/", payload(unit, shifts[1], metrics), format="json").status_code == 201


@pytest.mark.django_db
def test_out_of_range_values_and_future_reports_rejected(ops_client, unit, shifts, metrics):
    r = ops_client.post("/api/operations/reports/", payload(unit, shifts[0], metrics, avail="140"), format="json")
    assert r.status_code == 400 and "exceeds the valid maximum" in str(r.json())
    tomorrow = timezone.now().date() + dt.timedelta(days=2)
    r = ops_client.post("/api/operations/reports/", payload(unit, shifts[0], metrics, day=tomorrow), format="json")
    assert r.status_code == 400


@pytest.mark.django_db
def test_missing_values_need_a_reason_and_are_never_zero(users, unit, shifts, metrics):
    report = ops.create_report(user=users["OPERATIONS"], plant_unit=unit, shift=shifts[0], report_date=YESTERDAY,
                               measurements=[{"metric": metrics["energy"], "value": Decimal("800")}])
    with pytest.raises(ValidationError) as exc:
        ops.submit_report(report, user=users["OPERATIONS"])
    assert "Availability" in str(exc.value)
    ops.update_report(report, user=users["OPERATIONS"], measurements=[
        {"metric": metrics["energy"], "value": Decimal("800")},
        {"metric": metrics["avail"], "value": None, "missing_reason": "Meter fault"}])
    ops.submit_report(report, user=users["OPERATIONS"])
    m = report.measurements.get(metric=metrics["avail"])
    assert m.value is None and m.missing_reason == "Meter fault"


@pytest.mark.django_db
def test_reviewer_rules_unit_assignment_and_segregation(make_user, users, unit2, shifts, metrics, client_for, unit):
    report = ops.create_report(user=users["OPERATIONS"], plant_unit=unit, shift=shifts[0], report_date=YESTERDAY,
                               measurements=[{"metric": metrics["energy"], "value": Decimal("800")},
                                             {"metric": metrics["avail"], "value": Decimal("99")}])
    ops.submit_report(report, user=users["OPERATIONS"])
    other_sup = make_user("SUPERVISOR", "sup_other_unit", units=[unit2])
    with pytest.raises(ValidationError):
        ops.review_report(report, user=other_sup, approve=True)
    # Operations officers cannot review at all (server-side permission)
    r = client_for(users["OPERATIONS"]).post(f"/api/operations/reports/{report.pk}/review/", {"decision": "approve"},
                                             format="json")
    assert r.status_code == 403
    # Operations officers can only create reports for units assigned to them
    with pytest.raises(ValidationError):
        ops.create_report(user=users["OPERATIONS"], plant_unit=unit2, shift=shifts[0], report_date=YESTERDAY)


@pytest.mark.django_db
def test_management_sees_only_approved_reports(users, client_for, unit, shifts, metrics):
    draft = ops.create_report(user=users["OPERATIONS"], plant_unit=unit, shift=shifts[0], report_date=YESTERDAY)
    mgmt = client_for(users["MANAGEMENT"])
    assert mgmt.get("/api/operations/reports/").json()["count"] == 0
    assert mgmt.get(f"/api/operations/reports/{draft.pk}/").status_code == 404
    assert client_for(users["SUPERVISOR"]).get("/api/operations/reports/").json()["count"] == 1


@pytest.mark.django_db
def test_missing_report_detection(users, unit, shifts, metrics):
    day = timezone.now().date() - dt.timedelta(days=2)
    ops.create_report(user=users["OPERATIONS"], plant_unit=unit, shift=shifts[0], report_date=day)  # draft only
    gaps = ops.missing_reports(day, day)
    states = {(g["shift"], g["state"]) for g in gaps}
    assert (shifts[0].pk, "DRAFT_NOT_SUBMITTED") in states
    assert (shifts[1].pk, "MISSING") in states


@pytest.mark.django_db
def test_target_comparison(users, unit, shifts, metrics):
    report = ops.create_report(user=users["OPERATIONS"], plant_unit=unit, shift=shifts[0], report_date=YESTERDAY,
                               measurements=[{"metric": metrics["energy"], "value": Decimal("900")}])
    row = next(r for r in ops.target_comparison(report) if r["metric"] == "ENERGY")
    assert row["variance"] == "-100.0000" and row["variance_pct"] == "-10.0" and row["status"] == "BELOW_TARGET"
    assert OperationalReport.objects.count() == 1
