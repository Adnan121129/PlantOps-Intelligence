import datetime as dt
import threading
import uuid
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from apps.costs.models import OperationalExpense
from apps.inventory import services as inv
from apps.inventory.models import InventoryItem, PurchaseOrder, StockTransaction
from apps.maintenance import services as mnt


@pytest.fixture
def open_wo(users, asset, technician):
    wo = mnt.create_work_order(user=users["MAINTENANCE"], asset=asset, maintenance_type="CORRECTIVE", title="t",
                               description="d", reported_at=timezone.now() - dt.timedelta(hours=2))
    mnt.assign(wo, user=users["MAINTENANCE"], technician=technician)
    return wo


@pytest.mark.django_db
def test_ledger_receipt_issue_return_adjust(users, stocked_item, open_wo, mnt_dept):
    store = users["STORE"]
    inv.post_transaction(item_id=stocked_item.pk, txn_type="RECEIPT", quantity=10, unit_cost=Decimal("130"),
                         user=store, reference="DN-1")
    stocked_item.refresh_from_db()
    assert stocked_item.current_stock == 20 and stocked_item.unit_cost == Decimal("115.0000")  # weighted average
    inv.post_transaction(item_id=stocked_item.pk, txn_type="ISSUE", quantity=3, user=store, work_order=open_wo)
    inv.post_transaction(item_id=stocked_item.pk, txn_type="RETURN", quantity=1, user=store, work_order=open_wo)
    with pytest.raises(ValidationError, match="outstanding"):
        inv.post_transaction(item_id=stocked_item.pk, txn_type="RETURN", quantity=5, user=store, work_order=open_wo)
    with pytest.raises(ValidationError, match="reason"):
        inv.post_transaction(item_id=stocked_item.pk, txn_type="ADJUSTMENT", quantity=-1, user=store)
    inv.post_transaction(item_id=stocked_item.pk, txn_type="ADJUSTMENT", quantity=-1, user=store, notes="Damaged")
    stocked_item.refresh_from_db()
    assert stocked_item.current_stock == 17
    # the ledger re-sums to the balance and every row carries its running balance
    ledger = list(StockTransaction.objects.filter(item=stocked_item).order_by("occurred_at", "id"))
    assert sum(t.quantity for t in ledger) == stocked_item.current_stock
    assert ledger[-1].balance_after == stocked_item.current_stock
    # parts cost: issue 3 x 115 = 345, return credit 1 x 115
    wo_costs = OperationalExpense.objects.filter(work_order=open_wo).values_list("amount", flat=True)
    assert sorted(wo_costs) == [Decimal("-115.00"), Decimal("345.00")]


@pytest.mark.django_db
def test_negative_stock_and_invalid_quantities_rejected(users, stocked_item, open_wo):
    with pytest.raises(ValidationError, match="Insufficient stock"):
        inv.post_transaction(item_id=stocked_item.pk, txn_type="ISSUE", quantity=11, user=users["STORE"], work_order=open_wo)
    with pytest.raises(ValidationError, match="whole numbers"):
        inv.post_transaction(item_id=stocked_item.pk, txn_type="ISSUE", quantity="1.5", user=users["STORE"], work_order=open_wo)
    with pytest.raises(ValidationError, match="work order or a department"):
        inv.post_transaction(item_id=stocked_item.pk, txn_type="ISSUE", quantity=1, user=users["STORE"])
    with pytest.raises(ValidationError, match="back-dated"):
        inv.post_transaction(item_id=stocked_item.pk, txn_type="ADJUSTMENT", quantity=1, user=users["STORE"], notes="x",
                             occurred_at=timezone.now() - dt.timedelta(days=30))
    # database CHECK constraint is the final guard against negative stock
    with pytest.raises(IntegrityError), transaction.atomic():
        InventoryItem.objects.filter(pk=stocked_item.pk).update(current_stock=-1)


@pytest.mark.django_db
def test_stock_fields_not_writable_through_api(users, client_for, stocked_item):
    client = client_for(users["STORE"])
    r = client.patch(f"/api/inventory/items/{stocked_item.pk}/", {"current_stock": 999, "unit_cost": 1}, format="json")
    assert r.status_code == 200
    stocked_item.refresh_from_db()
    assert stocked_item.current_stock == 10 and stocked_item.unit_cost == Decimal("100.0000")
    assert client.delete(f"/api/inventory/transactions/{StockTransaction.objects.first().pk}/").status_code in (403, 405)


@pytest.mark.django_db
def test_transaction_permissions_by_type(users, client_for, stocked_item, open_wo):
    maint = client_for(users["MAINTENANCE"])
    r = maint.post("/api/inventory/transactions/", {"item": stocked_item.pk, "txn_type": "ADJUSTMENT", "quantity": "5",
                                                    "notes": "x"}, format="json")
    assert r.status_code == 403
    r = maint.post("/api/inventory/transactions/", {"item": stocked_item.pk, "txn_type": "ISSUE", "quantity": "1",
                                                    "work_order": open_wo.pk}, format="json")
    assert r.status_code == 201


@pytest.mark.django_db
def test_idempotent_retry_does_not_double_post(users, client_for, stocked_item, open_wo):
    client = client_for(users["STORE"])
    key = str(uuid.uuid4())
    body = {"item": stocked_item.pk, "txn_type": "ISSUE", "quantity": "2", "work_order": open_wo.pk, "idempotency_key": key}
    first = client.post("/api/inventory/transactions/", body, format="json")
    second = client.post("/api/inventory/transactions/", body, format="json")
    assert first.status_code == 201 and second.status_code == 200 and second.json()["duplicate"] is True
    assert first.json()["id"] == second.json()["id"]
    stocked_item.refresh_from_db()
    assert stocked_item.current_stock == 8


@pytest.mark.django_db(transaction=True)
def test_concurrent_issues_cannot_oversell(users, stocked_item, open_wo):
    """Twelve parallel requests for 1 unit each against 10 in stock: exactly 10 succeed."""
    results: list[str] = []
    barrier = threading.Barrier(12)

    def worker():
        try:
            barrier.wait()
            inv.post_transaction(item_id=stocked_item.pk, txn_type="ISSUE", quantity=1, user=users["STORE"],
                                 work_order=open_wo)
            results.append("ok")
        except ValidationError:
            results.append("rejected")
        finally:
            connection.close()

    threads = [threading.Thread(target=worker) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    stocked_item.refresh_from_db()
    assert results.count("ok") == 10 and results.count("rejected") == 2
    assert stocked_item.current_stock == 0
    assert StockTransaction.objects.filter(item=stocked_item, txn_type="ISSUE").count() == 10


@pytest.mark.django_db
def test_procurement_workflow_partial_receipts_and_duplicates(users, client_for, item, mnt_dept):
    maint, mgr, store = client_for(users["MAINTENANCE"]), client_for(users["MANAGEMENT"]), client_for(users["STORE"])
    r = maint.post("/api/inventory/purchase-requests/", {"justification": "Low stock", "lines": [
        {"item": item.pk, "quantity": "10", "estimated_unit_cost": "50"}]}, format="json")
    assert r.status_code == 201, r.json()
    pr = r.json()["id"]
    assert maint.post(f"/api/inventory/purchase-requests/{pr}/submit/").json()["status"] == "SUBMITTED"
    # requester cannot approve; store officer lacks the permission; management approves
    assert store.post(f"/api/inventory/purchase-requests/{pr}/decide/", {"decision": "approve"}, format="json").status_code == 403
    assert mgr.post(f"/api/inventory/purchase-requests/{pr}/decide/", {"decision": "approve"}, format="json").json()["status"] == "APPROVED"
    po = store.post(f"/api/inventory/purchase-requests/{pr}/convert/", {"supplier": item.preferred_supplier_id},
                    format="json").json()
    assert po["status"] == "DRAFT" and po["lines"][0]["unit_price"] == "50.0000"
    po = store.post(f"/api/inventory/purchase-orders/{po['id']}/issue/", {}, format="json").json()
    line = po["lines"][0]["id"]
    key = str(uuid.uuid4())
    r = store.post(f"/api/inventory/purchase-orders/{po['id']}/receive/", {"idempotency_key": key, "lines": [
        {"order_line": line, "quantity": "4"}]}, format="json")
    assert r.status_code == 201 and r.json()["status"] == "PARTIALLY_RECEIVED"
    again = store.post(f"/api/inventory/purchase-orders/{po['id']}/receive/", {"idempotency_key": key, "lines": [
        {"order_line": line, "quantity": "4"}]}, format="json")
    assert again.status_code == 200 and again.json()["receipt"]["duplicate"] is True
    item.refresh_from_db()
    assert item.current_stock == 4
    over = store.post(f"/api/inventory/purchase-orders/{po['id']}/receive/", {"lines": [
        {"order_line": line, "quantity": "7"}]}, format="json")
    assert over.status_code == 400 and "exceeds" in str(over.json())
    r = store.post(f"/api/inventory/purchase-orders/{po['id']}/receive/", {"lines": [{"order_line": line, "quantity": "6"}]},
                   format="json")
    assert r.json()["status"] == "RECEIVED"
    assert store.post(f"/api/inventory/purchase-orders/{po['id']}/close/", {}, format="json").json()["status"] == "CLOSED"
    item.refresh_from_db()
    assert item.current_stock == 10 and PurchaseOrder.objects.get(pk=po["id"]).receipts.count() == 2
    # receipts are inventory, not expense
    assert not OperationalExpense.objects.exists()


@pytest.mark.django_db
def test_requester_cannot_approve_own_request(users, item):
    pr = inv.create_purchase_request(user=users["MANAGEMENT"], justification="x",
                                     lines=[{"item": item, "quantity": 1}])
    inv.submit_purchase_request(pr, user=users["MANAGEMENT"])
    with pytest.raises(ValidationError, match="own"):
        inv.decide_purchase_request(pr, user=users["MANAGEMENT"], approve=True)
