import datetime as dt

import pytest
from django.utils import timezone

from apps.costs.models import OperationalExpense
from apps.inventory.services import post_transaction


@pytest.mark.django_db
def test_manual_expense_validation(users, client_for, asset):
    client = client_for(users["ADMIN"])
    today = timezone.now().date()
    base = {"expense_date": today.isoformat(), "category": "CONTRACTOR", "amount": "1500.00", "description": "Service"}
    assert client.post("/api/costs/expenses/", base, format="json").status_code == 201
    assert client.post("/api/costs/expenses/", {**base, "amount": "-1"}, format="json").status_code == 400
    assert client.post("/api/costs/expenses/", {**base, "amount": "1.005"}, format="json").status_code == 400
    assert client.post("/api/costs/expenses/", {**base, "currency": "EUR"}, format="json").status_code == 400
    future = (today + dt.timedelta(days=3)).isoformat()
    assert client.post("/api/costs/expenses/", {**base, "expense_date": future}, format="json").status_code == 400
    assert client.post("/api/costs/expenses/", {**base, "expense_date": future, "cost_type": "ESTIMATE"},
                       format="json").status_code == 201
    r = client.post("/api/costs/expenses/", {**base, "category": "SPARE_PARTS", "asset": asset.pk}, format="json")
    assert r.status_code == 400  # equipment parts must come through the stock ledger


@pytest.mark.django_db
def test_system_generated_costs_are_immutable(users, client_for, stocked_item, mnt_dept):
    post_transaction(item_id=stocked_item.pk, txn_type="ISSUE", quantity=1, user=users["STORE"], department=mnt_dept)
    expense = OperationalExpense.objects.get(source="STOCK")
    client = client_for(users["ADMIN"])
    assert client.patch(f"/api/costs/expenses/{expense.pk}/", {"amount": "1"}, format="json").status_code == 400
    assert client.delete(f"/api/costs/expenses/{expense.pk}/").status_code == 400


@pytest.mark.django_db
def test_budget_uniqueness_and_permissions(users, client_for):
    admin = client_for(users["ADMIN"])
    line = {"year": 2026, "month": 3, "category": "LABOR", "amount": "5000"}
    assert admin.post("/api/costs/budgets/", line, format="json").status_code == 201
    assert admin.post("/api/costs/budgets/", line, format="json").status_code == 400
    assert admin.post("/api/costs/budgets/", {**line, "month": 13}, format="json").status_code == 400
    assert client_for(users["MANAGEMENT"]).post("/api/costs/budgets/", {**line, "month": 4}, format="json").status_code == 403
