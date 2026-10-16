import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.costs.models import OperationalExpense
from apps.workforce.models import Employee, OvertimeRecord, ShiftAssignment
from apps.workforce.services import decide_overtime


@pytest.mark.django_db
def test_contact_details_hidden_from_unauthorised_roles(users, client_for, technician):
    technician.email, technician.phone = "t@example.invalid", "123"
    technician.save()
    row = client_for(users["MANAGEMENT"]).get(f"/api/workforce/employees/{technician.pk}/").json()
    assert "email" not in row and "hourly_rate" not in row
    row = client_for(users["SUPERVISOR"]).get(f"/api/workforce/employees/{technician.pk}/").json()
    assert row["email"] == "t@example.invalid"


@pytest.mark.django_db
def test_assignment_rules_and_coverage(users, client_for, technician, shifts, mnt_dept):
    client = client_for(users["SUPERVISOR"])
    day = timezone.now().date()
    r = client.post("/api/workforce/assignments/", {"employee": technician.pk, "shift": shifts[0].pk, "date": day},
                    format="json")
    assert r.status_code == 201
    dup = client.post("/api/workforce/assignments/", {"employee": technician.pk, "shift": shifts[1].pk, "date": day},
                      format="json")
    assert dup.status_code == 400
    inactive = Employee.objects.create(employee_code="X9", first_name="In", last_name="Active", department=mnt_dept,
                                       job_title="Op", employment_status="INACTIVE")
    assert client.post("/api/workforce/assignments/", {"employee": inactive.pk, "shift": shifts[0].pk, "date": day},
                       format="json").status_code == 400
    cov = client.get(f"/api/workforce/assignments/coverage/?date_from={day}&date_to={day}").json()
    status = {r["shift"]: r["status"] for r in cov["rows"]}
    assert status[shifts[0].pk] == "UNDERSTAFFED" and status[shifts[1].pk] == "UNASSIGNED"
    assert ShiftAssignment.objects.count() == 1


@pytest.mark.django_db
def test_overtime_approval_costs_and_posts_expense(users, make_user, technician):
    record = OvertimeRecord.objects.create(employee=technician, date=timezone.now().date() - dt.timedelta(days=1),
                                           hours=Decimal("4"), rate_multiplier=Decimal("1.5"), reason="Breakdown",
                                           recorded_by=users["SUPERVISOR"])
    with pytest.raises(ValidationError):
        decide_overtime(record, user=users["SUPERVISOR"], approve=True)   # not by the recorder
    other = make_user("SUPERVISOR", "sup2")
    decide_overtime(record, user=other, approve=True)
    record.refresh_from_db()
    assert record.cost == Decimal("240.00")                              # 4 h x 40 x 1.5
    expense = OperationalExpense.objects.get(overtime=record)
    assert expense.category == "LABOR" and expense.amount == Decimal("240.00") and expense.source == "OVERTIME"
    with pytest.raises(ValidationError):
        decide_overtime(record, user=other, approve=True)


@pytest.mark.django_db
def test_handover_acknowledged_by_incoming_shift(users, make_user, client_for, unit, shifts):
    author = client_for(users["OPERATIONS"])
    r = author.post("/api/workforce/handovers/", {"plant_unit": unit.pk, "shift": shifts[0].pk,
                                                  "date": timezone.now().date(), "summary": "Stable"}, format="json")
    assert r.status_code == 201
    hid = r.json()["id"]
    assert author.post(f"/api/workforce/handovers/{hid}/acknowledge/").status_code == 400
    other = client_for(make_user("OPERATIONS", "ops2"))
    assert other.post(f"/api/workforce/handovers/{hid}/acknowledge/").json()["received_by_name"] == "ops2"
