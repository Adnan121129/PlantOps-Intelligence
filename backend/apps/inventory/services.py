"""Stock ledger and procurement workflows.

All stock-changing operations go through `post_transaction`, which:
1. locks the item row (SELECT ... FOR UPDATE) so concurrent requests are serialised;
2. re-checks the idempotency key *after* acquiring the lock, so a retried request
   returns the original transaction instead of posting twice;
3. validates quantity, sign, available stock and chronological order;
4. writes the immutable ledger row and the new item balance in one DB transaction;
5. posts the cost-ledger entry for issues/returns.
"""
from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.accounts import audit
from apps.accounts.models import AuditLog
from apps.core import clock
from apps.core.numbering import next_number
from apps.core.period import plant_tz, resolve_plant
from apps.core.settings_registry import get_setting

from .models import (
    GoodsReceipt,
    GoodsReceiptLine,
    InventoryItem,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseRequest,
    PurchaseRequestLine,
    StockTransaction,
)

QTY = Decimal("0.001")
COST = Decimal("0.0001")
MONEY = Decimal("0.01")
INTEGRAL_UOMS = {InventoryItem.UOM.EACH, InventoryItem.UOM.SET, InventoryItem.UOM.BOX}
CLOCK_SKEW = dt.timedelta(minutes=5)

T = StockTransaction.TxnType


@dataclass
class PostResult:
    transaction: StockTransaction
    created: bool


def _to_decimal(value, field: str) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception as exc:  # noqa: BLE001 - any parse failure is a validation error
        raise ValidationError({field: "Enter a valid number."}) from exc


def _validate_quantity(item: InventoryItem, quantity: Decimal) -> Decimal:
    q = quantity.quantize(QTY, rounding=ROUND_HALF_UP)
    if q != quantity:
        raise ValidationError({"quantity": "At most 3 decimal places are allowed."})
    if item.uom in INTEGRAL_UOMS and q != q.to_integral_value():
        raise ValidationError({"quantity": f"Quantities in {item.get_uom_display()} must be whole numbers."})
    return q


def net_issued(item: InventoryItem, *, work_order=None, department=None) -> Decimal:
    """Quantity issued minus quantity returned for a work order (or department) and item."""
    qs = StockTransaction.objects.filter(item=item, txn_type__in=[T.ISSUE, T.RETURN])
    qs = qs.filter(work_order=work_order) if work_order is not None else qs.filter(department=department, work_order=None)
    total = qs.aggregate(s=Sum("quantity"))["s"] or Decimal(0)
    return -total


def _average_issue_cost(item: InventoryItem, *, work_order=None, department=None) -> Decimal:
    qs = StockTransaction.objects.filter(item=item, txn_type=T.ISSUE)
    qs = qs.filter(work_order=work_order) if work_order is not None else qs.filter(department=department, work_order=None)
    agg = qs.aggregate(q=Sum("quantity"), v=Sum("total_value"))
    if not agg["q"]:
        return item.unit_cost
    return (agg["v"] / agg["q"]).quantize(COST, rounding=ROUND_HALF_UP)


def post_transaction(
    *,
    item_id: int,
    txn_type: str,
    quantity,
    user,
    occurred_at: dt.datetime | None = None,
    unit_cost=None,
    work_order=None,
    department=None,
    reference: str = "",
    notes: str = "",
    idempotency_key: uuid.UUID | str | None = None,
    receipt_line: GoodsReceiptLine | None = None,
) -> PostResult:
    from apps.maintenance.models import WorkOrder

    if txn_type not in T.values:
        raise ValidationError({"txn_type": "Unknown transaction type."})
    quantity = _to_decimal(quantity, "quantity")
    now = timezone.now()
    explicit_time = occurred_at is not None
    if explicit_time and occurred_at > now + CLOCK_SKEW:
        raise ValidationError({"occurred_at": "Stock movements cannot be recorded in the future."})
    if idempotency_key is not None and not isinstance(idempotency_key, uuid.UUID):
        try:
            idempotency_key = uuid.UUID(str(idempotency_key))
        except ValueError as exc:
            raise ValidationError({"idempotency_key": "Must be a UUID."}) from exc

    with transaction.atomic():
        try:
            item = InventoryItem.objects.select_for_update().select_related("category").get(pk=item_id)
        except InventoryItem.DoesNotExist as exc:
            raise ValidationError({"item": "Unknown inventory item."}) from exc

        if idempotency_key is not None:
            existing = StockTransaction.objects.filter(idempotency_key=idempotency_key).first()
            if existing is not None:
                if existing.item_id != item.pk or existing.txn_type != txn_type:
                    raise ValidationError({"idempotency_key": "This key was already used for a different movement."})
                return PostResult(existing, False)

        if not explicit_time:
            # Timestamp taken after acquiring the lock, so requests that waited are never "back-dated".
            occurred_at = max(clock.now(), item.last_movement_at or clock.now())
        quantity = _validate_quantity(item, quantity)
        if txn_type == T.ADJUSTMENT:
            if quantity == 0:
                raise ValidationError({"quantity": "Adjustment quantity cannot be zero."})
            if not notes.strip():
                raise ValidationError({"notes": "A reason is required for stock adjustments."})
            signed = quantity
        else:
            if quantity <= 0:
                raise ValidationError({"quantity": "Quantity must be greater than zero."})
            signed = -quantity if txn_type == T.ISSUE else quantity

        if item.last_movement_at and occurred_at < item.last_movement_at:
            raise ValidationError({"occurred_at": (
                "Movements cannot be back-dated before the item's last recorded movement "
                f"({timezone.localtime(item.last_movement_at):%Y-%m-%d %H:%M}). Record an adjustment instead."
            )})

        if txn_type in (T.ISSUE, T.RETURN):
            if work_order is None and department is None:
                raise ValidationError({"work_order": "Issues and returns must reference a work order or a department."})
            if work_order is not None:
                work_order = WorkOrder.objects.select_for_update().get(pk=work_order.pk)
                if txn_type == T.ISSUE and work_order.status not in (WorkOrder.Status.ASSIGNED, WorkOrder.Status.IN_PROGRESS):
                    raise ValidationError({"work_order": "Parts can only be issued to assigned or in-progress work orders."})
                if work_order.status == WorkOrder.Status.CANCELLED:
                    raise ValidationError({"work_order": "The work order is cancelled."})
        if txn_type == T.ISSUE and not item.is_active:
            raise ValidationError({"item": "Inactive items cannot be issued."})

        if txn_type == T.RECEIPT:
            if unit_cost is None:
                raise ValidationError({"unit_cost": "Unit cost is required for receipts."})
            unit_cost = _to_decimal(unit_cost, "unit_cost").quantize(COST, rounding=ROUND_HALF_UP)
            if unit_cost < 0:
                raise ValidationError({"unit_cost": "Unit cost cannot be negative."})
        elif txn_type == T.RETURN:
            outstanding = net_issued(item, work_order=work_order, department=None if work_order else department)
            if quantity > outstanding:
                raise ValidationError({"quantity": f"Only {outstanding.normalize()} {item.uom} are outstanding on this "
                                                   "reference and can be returned."})
            unit_cost = _average_issue_cost(item, work_order=work_order, department=None if work_order else department)
        else:
            unit_cost = item.unit_cost

        new_balance = item.current_stock + signed
        if new_balance < 0:
            raise ValidationError({"quantity": f"Insufficient stock: {item.current_stock.normalize()} {item.uom} available."})

        if txn_type == T.RECEIPT:
            # Weighted-average cost: (old qty x old cost + received qty x price) / new qty.
            if new_balance > 0:
                item.unit_cost = ((item.current_stock * item.unit_cost + quantity * unit_cost) / new_balance).quantize(
                    COST, rounding=ROUND_HALF_UP)
        total_value = (signed * unit_cost).quantize(MONEY, rounding=ROUND_HALF_UP)

        txn = StockTransaction.objects.create(
            txn_number=next_number("ST", width=6, year=occurred_at.year),
            item=item,
            txn_type=txn_type,
            quantity=signed,
            unit_cost=unit_cost,
            total_value=total_value,
            balance_after=new_balance,
            occurred_at=occurred_at,
            reference=reference[:80],
            work_order=work_order,
            department=department,
            receipt_line=receipt_line,
            recorded_by=user,
            notes=notes,
            idempotency_key=idempotency_key,
        )
        item.current_stock = new_balance
        item.last_movement_at = occurred_at
        item.save(update_fields=["current_stock", "unit_cost", "last_movement_at", "updated_at"])

        if txn_type in (T.ISSUE, T.RETURN) and total_value != 0:
            _post_stock_expense(txn, item, work_order, department, user)

        audit.record(user, AuditLog.Action.STOCK, txn, changes={
            "item": item.item_code, "type": txn_type, "quantity": str(signed), "balance_after": str(new_balance),
            "unit_cost": str(unit_cost),
        }, message=notes[:500])
        transaction.on_commit(_evaluate_stock_alerts)
    return PostResult(txn, True)


def _post_stock_expense(txn: StockTransaction, item: InventoryItem, work_order, department, user) -> None:
    from apps.costs.models import CostCategory, OperationalExpense
    from apps.costs.services import maintenance_department

    plant = work_order.asset.plant_unit.plant if work_order is not None else resolve_plant(None)
    local_date = txn.occurred_at.astimezone(plant_tz(plant)).date()
    verb = "Issued" if txn.txn_type == T.ISSUE else "Returned"
    OperationalExpense.objects.create(
        expense_date=local_date,
        category=CostCategory.CONSUMABLES if item.category.is_consumable else CostCategory.SPARE_PARTS,
        cost_type=OperationalExpense.CostType.ACTUAL,
        amount=-txn.total_value,  # issue: positive cost; return: negative credit
        currency=get_setting("base_currency"),
        description=f"{verb} {abs(txn.quantity).normalize()} {item.uom} {item.item_code} {item.name}"[:255],
        reference=txn.txn_number,
        asset=work_order.asset if work_order is not None else None,
        work_order=work_order,
        department=department if work_order is None else (department or maintenance_department()),
        plant_unit=work_order.asset.plant_unit if work_order is not None else None,
        source=OperationalExpense.Source.STOCK,
        stock_transaction=txn,
        recorded_by=user,
    )


def _evaluate_stock_alerts() -> None:
    from apps.alerts.engine import evaluate_rules

    evaluate_rules(["LOW_STOCK", "CRITICAL_STOCK"])


# --------------------------------------------------------------------------- procurement


def _ensure_status(obj, allowed, action: str) -> None:
    if obj.status not in allowed:
        raise ValidationError(f"Cannot {action} while the record is '{obj.get_status_display()}'.")


@transaction.atomic
def create_purchase_request(*, user, justification: str, lines: list[dict], department=None, needed_by=None) -> PurchaseRequest:
    if not lines:
        raise ValidationError({"lines": "Add at least one item."})
    item_ids = [line["item"].pk for line in lines]
    if len(item_ids) != len(set(item_ids)):
        raise ValidationError({"lines": "Each item may appear only once; combine the quantities."})
    if needed_by and needed_by < clock.now().astimezone(timezone.get_current_timezone()).date():
        raise ValidationError({"needed_by": "The required-by date cannot be in the past."})
    pr = PurchaseRequest.objects.create(
        pr_number=next_number("PR"), requested_by=user, department=department, justification=justification,
        needed_by=needed_by,
    )
    _write_pr_lines(pr, lines)
    audit.record(user, AuditLog.Action.CREATE, pr, changes={"lines": len(lines)})
    return pr


def _write_pr_lines(pr: PurchaseRequest, lines: list[dict]) -> None:
    pr.lines.all().delete()
    for line in lines:
        item = line["item"]
        qty = _validate_quantity(item, _to_decimal(line["quantity"], "quantity"))
        if qty <= 0:
            raise ValidationError({"lines": "Quantities must be greater than zero."})
        PurchaseRequestLine.objects.create(
            request=pr, item=item, quantity=qty,
            estimated_unit_cost=line.get("estimated_unit_cost") if line.get("estimated_unit_cost") is not None else item.unit_cost,
            note=line.get("note", ""),
        )


@transaction.atomic
def update_purchase_request(pr: PurchaseRequest, *, user, justification=None, lines=None, needed_by=None, department=None):
    pr = PurchaseRequest.objects.select_for_update().get(pk=pr.pk)
    _ensure_status(pr, [PurchaseRequest.Status.DRAFT, PurchaseRequest.Status.REJECTED], "edit the request")
    if pr.requested_by_id != user.pk:
        raise ValidationError("Only the requester can edit this purchase request.")
    if justification is not None:
        pr.justification = justification
    if needed_by is not None:
        pr.needed_by = needed_by
    if department is not None:
        pr.department = department
    pr.save()
    if lines is not None:
        if not lines:
            raise ValidationError({"lines": "Add at least one item."})
        _write_pr_lines(pr, lines)
    audit.record(user, AuditLog.Action.UPDATE, pr)
    return pr


@transaction.atomic
def submit_purchase_request(pr: PurchaseRequest, *, user) -> PurchaseRequest:
    from apps.alerts.notify import notify_role

    pr = PurchaseRequest.objects.select_for_update().get(pk=pr.pk)
    _ensure_status(pr, [PurchaseRequest.Status.DRAFT, PurchaseRequest.Status.REJECTED], "submit")
    if pr.requested_by_id != user.pk:
        raise ValidationError("Only the requester can submit this purchase request.")
    if not pr.lines.exists():
        raise ValidationError({"lines": "Add at least one item before submitting."})
    before = pr.status
    pr.status = PurchaseRequest.Status.SUBMITTED
    pr.submitted_at = clock.now()
    pr.save()
    audit.record_approval(pr, action="SUBMIT", actor=user, from_status=before, to_status=pr.status)
    notify_role("MANAGEMENT", f"Purchase request {pr.pr_number} awaits approval", pr.justification[:200],
                f"/procurement/requests/{pr.pk}")
    return pr


@transaction.atomic
def decide_purchase_request(pr: PurchaseRequest, *, user, approve: bool, comment: str = "") -> PurchaseRequest:
    from apps.alerts.notify import notify

    pr = PurchaseRequest.objects.select_for_update().get(pk=pr.pk)
    _ensure_status(pr, [PurchaseRequest.Status.SUBMITTED], "decide on the request")
    if pr.requested_by_id == user.pk:
        raise ValidationError("You cannot approve or reject your own purchase request.")
    if not approve and not comment.strip():
        raise ValidationError({"comment": "A reason is required when rejecting."})
    before = pr.status
    pr.status = PurchaseRequest.Status.APPROVED if approve else PurchaseRequest.Status.REJECTED
    pr.decided_by, pr.decided_at, pr.decision_comment = user, clock.now(), comment
    pr.save()
    audit.record_approval(pr, action="APPROVE" if approve else "REJECT", actor=user, from_status=before,
                          to_status=pr.status, comment=comment)
    audit.record(user, AuditLog.Action.APPROVE if approve else AuditLog.Action.REJECT, pr, message=comment)
    notify([pr.requested_by], f"Purchase request {pr.pr_number} {pr.get_status_display().lower()}", comment,
           f"/procurement/requests/{pr.pk}")
    return pr


@transaction.atomic
def convert_to_purchase_order(pr: PurchaseRequest, *, user, supplier, expected_delivery_date=None,
                              prices: dict[int, Decimal] | None = None) -> PurchaseOrder:
    pr = PurchaseRequest.objects.select_for_update().get(pk=pr.pk)
    _ensure_status(pr, [PurchaseRequest.Status.APPROVED], "create a purchase order")
    if not supplier.is_active:
        raise ValidationError({"supplier": "The supplier is inactive."})
    prices = prices or {}
    po = PurchaseOrder.objects.create(
        po_number=next_number("PO"), supplier=supplier, purchase_request=pr, currency=get_setting("base_currency"),
        expected_delivery_date=expected_delivery_date, created_by=user,
    )
    for line in pr.lines.select_related("item"):
        price = prices.get(line.item_id, line.estimated_unit_cost if line.estimated_unit_cost is not None else line.item.unit_cost)
        price = _to_decimal(price, "unit_price")
        if price < 0:
            raise ValidationError({"prices": "Prices cannot be negative."})
        PurchaseOrderLine.objects.create(order=po, item=line.item, quantity_ordered=line.quantity, unit_price=price)
    pr.status = PurchaseRequest.Status.ORDERED
    pr.save(update_fields=["status", "updated_at"])
    audit.record(user, AuditLog.Action.CREATE, po, message=f"Created from {pr.pr_number}")
    return po


@transaction.atomic
def issue_purchase_order(po: PurchaseOrder, *, user, order_date: dt.date | None = None, expected_delivery_date=None):
    po = PurchaseOrder.objects.select_for_update().get(pk=po.pk)
    _ensure_status(po, [PurchaseOrder.Status.DRAFT], "issue the order")
    if not po.lines.exists():
        raise ValidationError("The purchase order has no lines.")
    order_date = order_date or clock.now().astimezone(timezone.get_current_timezone()).date()
    if order_date > timezone.localdate():
        raise ValidationError({"order_date": "The order date cannot be in the future."})
    if expected_delivery_date is not None:
        po.expected_delivery_date = expected_delivery_date
    if po.expected_delivery_date and po.expected_delivery_date < order_date:
        raise ValidationError({"expected_delivery_date": "Expected delivery cannot be before the order date."})
    po.status, po.order_date = PurchaseOrder.Status.ISSUED, order_date
    po.save()
    audit.record(user, AuditLog.Action.STATUS, po, changes={"status": {"from": "DRAFT", "to": "ISSUED"}})
    return po


@dataclass
class ReceiveResult:
    receipt: GoodsReceipt
    created: bool


def receive_goods(po: PurchaseOrder, *, user, lines: list[dict], received_at: dt.datetime | None = None,
                  delivery_note: str = "", notes: str = "", idempotency_key=None) -> ReceiveResult:
    """Record a (partial) delivery. Repeating a submission with the same idempotency key is a no-op."""
    if received_at is not None and received_at > timezone.now() + CLOCK_SKEW:
        raise ValidationError({"received_at": "Receipts cannot be recorded in the future."})
    if idempotency_key is not None and not isinstance(idempotency_key, uuid.UUID):
        try:
            idempotency_key = uuid.UUID(str(idempotency_key))
        except ValueError as exc:
            raise ValidationError({"idempotency_key": "Must be a UUID."}) from exc

    with transaction.atomic():
        po = PurchaseOrder.objects.select_for_update().get(pk=po.pk)
        received_at = received_at or clock.now()
        if idempotency_key is not None:
            existing = GoodsReceipt.objects.filter(idempotency_key=idempotency_key).first()
            if existing is not None:
                if existing.order_id != po.pk:
                    raise ValidationError({"idempotency_key": "This key was already used for another order."})
                return ReceiveResult(existing, False)
        _ensure_status(po, [PurchaseOrder.Status.ISSUED, PurchaseOrder.Status.PARTIALLY_RECEIVED], "receive goods")
        if po.order_date and received_at.astimezone(timezone.get_current_timezone()).date() < po.order_date:
            raise ValidationError({"received_at": "Goods cannot be received before the order date."})
        if not lines:
            raise ValidationError({"lines": "Enter at least one received quantity."})
        line_ids = [int(line["order_line"]) for line in lines]
        if len(line_ids) != len(set(line_ids)):
            raise ValidationError({"lines": "Each order line may appear only once per receipt."})
        locked = {l.pk: l for l in PurchaseOrderLine.objects.select_for_update().select_related("item")
                  .filter(order=po, pk__in=line_ids)}
        if len(locked) != len(line_ids):
            raise ValidationError({"lines": "One or more lines do not belong to this purchase order."})

        receipt = GoodsReceipt.objects.create(
            receipt_number=next_number("GR"), order=po, received_at=received_at, received_by=user,
            delivery_note=delivery_note, notes=notes, idempotency_key=idempotency_key or uuid.uuid4(),
        )
        for line in lines:
            po_line = locked[int(line["order_line"])]
            qty = _validate_quantity(po_line.item, _to_decimal(line["quantity"], "quantity"))
            if qty <= 0:
                raise ValidationError({"lines": "Received quantities must be greater than zero."})
            if qty > po_line.outstanding:
                raise ValidationError({"lines": f"{po_line.item.item_code}: receiving {qty.normalize()} exceeds the "
                                                f"outstanding {po_line.outstanding.normalize()}."})
            receipt_line = GoodsReceiptLine.objects.create(receipt=receipt, order_line=po_line, quantity=qty)
            post_transaction(
                item_id=po_line.item_id, txn_type=T.RECEIPT, quantity=qty, unit_cost=po_line.unit_price, user=user,
                occurred_at=received_at, reference=f"{po.po_number}/{receipt.receipt_number}", receipt_line=receipt_line,
            )
            po_line.quantity_received += qty
            po_line.save(update_fields=["quantity_received"])

        fully = all(l.quantity_received >= l.quantity_ordered for l in po.lines.all())
        before = po.status
        po.status = PurchaseOrder.Status.RECEIVED if fully else PurchaseOrder.Status.PARTIALLY_RECEIVED
        if fully:
            po.fully_received_at = received_at
        po.save()
        audit.record(user, AuditLog.Action.STOCK, receipt, entity_repr=receipt.receipt_number,
                     changes={"po": po.po_number, "status": {"from": before, "to": po.status}})
    return ReceiveResult(receipt, True)


@transaction.atomic
def close_purchase_order(po: PurchaseOrder, *, user, reason: str = "") -> PurchaseOrder:
    po = PurchaseOrder.objects.select_for_update().get(pk=po.pk)
    _ensure_status(po, [PurchaseOrder.Status.RECEIVED, PurchaseOrder.Status.PARTIALLY_RECEIVED], "close the order")
    if po.status == PurchaseOrder.Status.PARTIALLY_RECEIVED and not reason.strip():
        raise ValidationError({"reason": "A reason is required to close an order that is not fully received."})
    before = po.status
    po.status, po.closed_at, po.close_reason = PurchaseOrder.Status.CLOSED, clock.now(), reason
    po.save()
    audit.record(user, AuditLog.Action.STATUS, po, changes={"status": {"from": before, "to": po.status}}, message=reason)
    return po


@transaction.atomic
def cancel_purchase_order(po: PurchaseOrder, *, user, reason: str) -> PurchaseOrder:
    po = PurchaseOrder.objects.select_for_update().get(pk=po.pk)
    _ensure_status(po, [PurchaseOrder.Status.DRAFT, PurchaseOrder.Status.ISSUED], "cancel the order")
    if not reason.strip():
        raise ValidationError({"reason": "A cancellation reason is required."})
    if po.receipts.exists():
        raise ValidationError("Orders with receipts cannot be cancelled; close them instead.")
    before = po.status
    po.status, po.closed_at, po.close_reason = PurchaseOrder.Status.CANCELLED, clock.now(), reason
    po.save()
    audit.record(user, AuditLog.Action.STATUS, po, changes={"status": {"from": before, "to": po.status}}, message=reason)
    return po
