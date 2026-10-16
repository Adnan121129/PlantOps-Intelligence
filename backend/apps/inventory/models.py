"""Inventory and procurement.

Stock-ledger rules
------------------
* `InventoryItem.current_stock` and `unit_cost` are maintained *only* by
  apps.inventory.services.post_transaction, inside a transaction holding a row lock
  on the item (SELECT ... FOR UPDATE). Serializers expose them read-only.
* Every movement is an immutable StockTransaction carrying the signed quantity and
  the resulting balance, so the ledger can always be re-summed and reconciled.
* Stock may not go negative (database CHECK constraint + service validation).
* Valuation uses the weighted-average cost, recalculated on each receipt.
* Requests may carry an idempotency key; a repeated key returns the original
  transaction instead of posting twice.
"""
from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.db.models import F, Q

from apps.assets.models import EquipmentAsset
from apps.core.models import Department, TimeStampedModel


class ItemCategory(TimeStampedModel):
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=120)
    is_consumable = models.BooleanField(default=False, help_text="Issues are costed as consumables, not spare parts.")

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "item categories"

    def __str__(self) -> str:
        return self.name


class Supplier(TimeStampedModel):
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=150)
    contact_name = models.CharField(max_length=120, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    address = models.TextField(blank=True)
    quoted_lead_time_days = models.PositiveIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class InventoryItem(TimeStampedModel):
    class Criticality(models.TextChoices):
        CRITICAL = "CRITICAL", "Critical spare"
        STANDARD = "STANDARD", "Standard"

    class UOM(models.TextChoices):
        EACH = "EA", "Each"
        SET = "SET", "Set"
        KG = "KG", "Kilogram"
        LITRE = "L", "Litre"
        METRE = "M", "Metre"
        BOX = "BOX", "Box"

    item_code = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    category = models.ForeignKey(ItemCategory, on_delete=models.PROTECT, related_name="items")
    uom = models.CharField(max_length=5, choices=UOM.choices, default=UOM.EACH)
    current_stock = models.DecimalField(max_digits=14, decimal_places=3, default=0, editable=False)
    unit_cost = models.DecimalField(max_digits=14, decimal_places=4, default=0, editable=False,
                                    help_text="Weighted-average cost, maintained by the stock ledger.")
    min_stock_level = models.DecimalField(max_digits=14, decimal_places=3, default=0,
                                          help_text="Reorder point. At or below this level the item is low on stock.")
    reorder_quantity = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    storage_location = models.CharField(max_length=80, blank=True)
    preferred_supplier = models.ForeignKey(Supplier, null=True, blank=True, on_delete=models.SET_NULL, related_name="items")
    compatible_assets = models.ManyToManyField(EquipmentAsset, blank=True, related_name="spare_parts")
    compatibility_notes = models.TextField(blank=True)
    criticality = models.CharField(max_length=10, choices=Criticality.choices, default=Criticality.STANDARD)
    last_movement_at = models.DateTimeField(null=True, blank=True, editable=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["item_code"]
        constraints = [
            models.CheckConstraint(condition=Q(current_stock__gte=0), name="item_stock_non_negative"),
            models.CheckConstraint(condition=Q(min_stock_level__gte=0) & Q(reorder_quantity__gte=0),
                                   name="item_levels_non_negative"),
            models.CheckConstraint(condition=Q(unit_cost__gte=0), name="item_cost_non_negative"),
        ]

    def __str__(self) -> str:
        return f"{self.item_code} {self.name}"

    @property
    def stock_status(self) -> str:
        if self.current_stock <= 0:
            return "OUT_OF_STOCK"
        if self.current_stock <= self.min_stock_level:
            return "CRITICAL_LOW" if self.criticality == self.Criticality.CRITICAL else "LOW"
        return "OK"


class StockTransaction(models.Model):
    class TxnType(models.TextChoices):
        RECEIPT = "RECEIPT", "Receipt"
        ISSUE = "ISSUE", "Issue"
        RETURN = "RETURN", "Return to store"
        ADJUSTMENT = "ADJUSTMENT", "Adjustment"

    txn_number = models.CharField(max_length=20, unique=True)
    item = models.ForeignKey(InventoryItem, on_delete=models.PROTECT, related_name="transactions")
    txn_type = models.CharField(max_length=10, choices=TxnType.choices, db_index=True)
    quantity = models.DecimalField(max_digits=14, decimal_places=3, help_text="Signed: + into store, - out of store.")
    unit_cost = models.DecimalField(max_digits=14, decimal_places=4)
    total_value = models.DecimalField(max_digits=16, decimal_places=2)
    balance_after = models.DecimalField(max_digits=14, decimal_places=3)
    occurred_at = models.DateTimeField(db_index=True)
    recorded_at = models.DateTimeField(auto_now_add=True)
    reference = models.CharField(max_length=80, blank=True, help_text="External document, e.g. delivery note.")
    work_order = models.ForeignKey("maintenance.WorkOrder", null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="stock_transactions")
    department = models.ForeignKey(Department, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    receipt_line = models.OneToOneField("GoodsReceiptLine", null=True, blank=True, on_delete=models.PROTECT,
                                        related_name="stock_transaction")
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    notes = models.TextField(blank=True)
    idempotency_key = models.UUIDField(null=True, blank=True, unique=True)

    class Meta:
        ordering = ["-occurred_at", "-id"]
        constraints = [
            models.CheckConstraint(condition=~Q(quantity=0), name="txn_quantity_non_zero"),
            models.CheckConstraint(condition=Q(balance_after__gte=0), name="txn_balance_non_negative"),
            models.CheckConstraint(
                condition=(Q(txn_type__in=["RECEIPT", "RETURN"], quantity__gt=0) | Q(txn_type="ISSUE", quantity__lt=0)
                           | Q(txn_type="ADJUSTMENT")),
                name="txn_sign_matches_type",
            ),
        ]
        indexes = [models.Index(fields=["item", "occurred_at"]), models.Index(fields=["work_order"])]

    def __str__(self) -> str:
        return f"{self.txn_number} {self.txn_type} {self.quantity}"


class PurchaseRequest(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SUBMITTED = "SUBMITTED", "Pending approval"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        ORDERED = "ORDERED", "Converted to purchase order"
        CANCELLED = "CANCELLED", "Cancelled"

    pr_number = models.CharField(max_length=20, unique=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT, db_index=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    department = models.ForeignKey(Department, null=True, blank=True, on_delete=models.PROTECT)
    justification = models.TextField()
    needed_by = models.DateField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_comment = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.pr_number


class PurchaseRequestLine(models.Model):
    request = models.ForeignKey(PurchaseRequest, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey(InventoryItem, on_delete=models.PROTECT, related_name="+")
    quantity = models.DecimalField(max_digits=14, decimal_places=3)
    estimated_unit_cost = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(quantity__gt=0), name="pr_line_qty_positive"),
            models.UniqueConstraint(fields=["request", "item"], name="uniq_pr_line_item"),
        ]


class PurchaseOrder(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        ISSUED = "ISSUED", "Issued to supplier"
        PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED", "Partially received"
        RECEIVED = "RECEIVED", "Fully received"
        CLOSED = "CLOSED", "Closed"
        CANCELLED = "CANCELLED", "Cancelled"

    po_number = models.CharField(max_length=20, unique=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="purchase_orders")
    purchase_request = models.OneToOneField(PurchaseRequest, null=True, blank=True, on_delete=models.PROTECT,
                                            related_name="purchase_order")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)
    order_date = models.DateField(null=True, blank=True, help_text="Date the order was issued to the supplier.")
    expected_delivery_date = models.DateField(null=True, blank=True)
    currency = models.CharField(max_length=3)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    fully_received_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    close_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.po_number


class PurchaseOrderLine(models.Model):
    order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey(InventoryItem, on_delete=models.PROTECT, related_name="po_lines")
    quantity_ordered = models.DecimalField(max_digits=14, decimal_places=3)
    unit_price = models.DecimalField(max_digits=14, decimal_places=4)
    quantity_received = models.DecimalField(max_digits=14, decimal_places=3, default=0, editable=False)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(quantity_ordered__gt=0), name="po_line_qty_positive"),
            models.CheckConstraint(condition=Q(unit_price__gte=0), name="po_line_price_non_negative"),
            models.CheckConstraint(condition=Q(quantity_received__gte=0) & Q(quantity_received__lte=F("quantity_ordered")),
                                   name="po_line_received_within_ordered"),
            models.UniqueConstraint(fields=["order", "item"], name="uniq_po_line_item"),
        ]

    @property
    def outstanding(self):
        return self.quantity_ordered - self.quantity_received


class GoodsReceipt(models.Model):
    receipt_number = models.CharField(max_length=20, unique=True)
    order = models.ForeignKey(PurchaseOrder, on_delete=models.PROTECT, related_name="receipts")
    received_at = models.DateTimeField()
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    delivery_note = models.CharField(max_length=80, blank=True)
    notes = models.TextField(blank=True)
    idempotency_key = models.UUIDField(default=uuid.uuid4, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-received_at"]


class GoodsReceiptLine(models.Model):
    receipt = models.ForeignKey(GoodsReceipt, on_delete=models.CASCADE, related_name="lines")
    order_line = models.ForeignKey(PurchaseOrderLine, on_delete=models.PROTECT, related_name="receipt_lines")
    quantity = models.DecimalField(max_digits=14, decimal_places=3)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(quantity__gt=0), name="receipt_line_qty_positive")]
