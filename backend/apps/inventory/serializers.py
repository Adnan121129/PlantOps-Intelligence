from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers

from apps.accounts.serializers import ApprovalRecordSerializer
from apps.core.models import Department
from apps.maintenance.models import WorkOrder

from .models import (
    GoodsReceipt,
    InventoryItem,
    ItemCategory,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseRequest,
    PurchaseRequestLine,
    StockTransaction,
    Supplier,
)


class ItemCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ItemCategory
        fields = ["id", "code", "name", "is_consumable"]


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = ["id", "code", "name", "contact_name", "email", "phone", "address", "quoted_lead_time_days", "is_active"]


class InventoryItemSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    supplier_name = serializers.CharField(source="preferred_supplier.name", read_only=True, default=None)
    stock_status = serializers.CharField(read_only=True)
    stock_value = serializers.SerializerMethodField()
    uom_label = serializers.CharField(source="get_uom_display", read_only=True)

    class Meta:
        model = InventoryItem
        fields = ["id", "item_code", "name", "description", "category", "category_name", "uom", "uom_label",
                  "current_stock", "unit_cost", "stock_value", "min_stock_level", "reorder_quantity", "storage_location",
                  "preferred_supplier", "supplier_name", "compatible_assets", "compatibility_notes", "criticality",
                  "stock_status", "last_movement_at", "is_active"]
        # Stock and cost are ledger-maintained: never writable through this API.
        read_only_fields = ["current_stock", "unit_cost", "last_movement_at"]

    def get_stock_value(self, obj) -> str:
        return str((obj.current_stock * obj.unit_cost).quantize(Decimal("0.01")))

    def validate(self, attrs):
        for field in ("min_stock_level", "reorder_quantity"):
            if field in attrs and attrs[field] < 0:
                raise serializers.ValidationError({field: "Cannot be negative."})
        return attrs


class StockTransactionSerializer(serializers.ModelSerializer):
    item_code = serializers.CharField(source="item.item_code", read_only=True)
    item_name = serializers.CharField(source="item.name", read_only=True)
    uom = serializers.CharField(source="item.uom", read_only=True)
    work_order_number = serializers.CharField(source="work_order.number", read_only=True, default=None)
    department_name = serializers.CharField(source="department.name", read_only=True, default=None)
    recorded_by_name = serializers.CharField(source="recorded_by.display_name", read_only=True)
    txn_type_label = serializers.CharField(source="get_txn_type_display", read_only=True)

    class Meta:
        model = StockTransaction
        fields = ["id", "txn_number", "item", "item_code", "item_name", "uom", "txn_type", "txn_type_label", "quantity",
                  "unit_cost", "total_value", "balance_after", "occurred_at", "recorded_at", "reference", "work_order",
                  "work_order_number", "department", "department_name", "recorded_by", "recorded_by_name", "notes"]


class StockTransactionInputSerializer(serializers.Serializer):
    item = serializers.PrimaryKeyRelatedField(queryset=InventoryItem.objects.all())
    txn_type = serializers.ChoiceField(choices=StockTransaction.TxnType.choices)
    quantity = serializers.DecimalField(max_digits=14, decimal_places=3,
                                        help_text="Positive magnitude; signed (+/-) for adjustments.")
    unit_cost = serializers.DecimalField(max_digits=14, decimal_places=4, required=False, allow_null=True)
    occurred_at = serializers.DateTimeField(required=False)
    reference = serializers.CharField(max_length=80, required=False, allow_blank=True, default="")
    work_order = serializers.PrimaryKeyRelatedField(queryset=WorkOrder.objects.all(),
                                                    required=False, allow_null=True)
    department = serializers.PrimaryKeyRelatedField(queryset=Department.objects.all(),
                                                    required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    idempotency_key = serializers.UUIDField(required=False, allow_null=True)


class PRLineSerializer(serializers.ModelSerializer):
    item_code = serializers.CharField(source="item.item_code", read_only=True)
    item_name = serializers.CharField(source="item.name", read_only=True)
    uom = serializers.CharField(source="item.uom", read_only=True)

    class Meta:
        model = PurchaseRequestLine
        fields = ["id", "item", "item_code", "item_name", "uom", "quantity", "estimated_unit_cost", "note"]


class PurchaseRequestSerializer(serializers.ModelSerializer):
    lines = PRLineSerializer(many=True)
    requested_by_name = serializers.CharField(source="requested_by.display_name", read_only=True)
    decided_by_name = serializers.CharField(source="decided_by.display_name", read_only=True, default=None)
    department_name = serializers.CharField(source="department.name", read_only=True, default=None)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    estimated_total = serializers.SerializerMethodField()
    purchase_order = serializers.SerializerMethodField()
    approvals = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseRequest
        fields = ["id", "pr_number", "status", "status_label", "requested_by", "requested_by_name", "department",
                  "department_name", "justification", "needed_by", "submitted_at", "decided_by_name", "decided_at",
                  "decision_comment", "lines", "estimated_total", "purchase_order", "approvals", "created_at"]
        read_only_fields = ["pr_number", "status", "requested_by", "submitted_at", "decided_at", "decision_comment"]

    def get_estimated_total(self, obj) -> str:
        total = sum(((l.estimated_unit_cost or Decimal(0)) * l.quantity for l in obj.lines.all()), Decimal(0))
        return str(total.quantize(Decimal("0.01")))

    def get_purchase_order(self, obj):
        po = getattr(obj, "purchase_order", None)
        return {"id": po.pk, "po_number": po.po_number, "status": po.status} if po else None

    def get_approvals(self, obj):
        from apps.accounts.audit import approvals_for

        return ApprovalRecordSerializer(approvals_for(obj), many=True).data


class POLineSerializer(serializers.ModelSerializer):
    item_code = serializers.CharField(source="item.item_code", read_only=True)
    item_name = serializers.CharField(source="item.name", read_only=True)
    uom = serializers.CharField(source="item.uom", read_only=True)
    outstanding = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    line_total = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseOrderLine
        fields = ["id", "item", "item_code", "item_name", "uom", "quantity_ordered", "unit_price", "quantity_received",
                  "outstanding", "line_total"]

    def get_line_total(self, obj) -> str:
        return str((obj.quantity_ordered * obj.unit_price).quantize(Decimal("0.01")))


class GoodsReceiptSerializer(serializers.ModelSerializer):
    received_by_name = serializers.CharField(source="received_by.display_name", read_only=True)
    po_number = serializers.CharField(source="order.po_number", read_only=True)
    lines = serializers.SerializerMethodField()

    class Meta:
        model = GoodsReceipt
        fields = ["id", "receipt_number", "order", "po_number", "received_at", "received_by_name", "delivery_note",
                  "notes", "lines"]

    def get_lines(self, obj):
        return [{"order_line": l.order_line_id, "item_code": l.order_line.item.item_code,
                 "item_name": l.order_line.item.name, "quantity": str(l.quantity)}
                for l in obj.lines.select_related("order_line__item")]


class PurchaseOrderSerializer(serializers.ModelSerializer):
    lines = POLineSerializer(many=True, read_only=True)
    receipts = GoodsReceiptSerializer(many=True, read_only=True)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    pr_number = serializers.CharField(source="purchase_request.pr_number", read_only=True, default=None)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    created_by_name = serializers.CharField(source="created_by.display_name", read_only=True)
    order_total = serializers.SerializerMethodField()
    received_value = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseOrder
        fields = ["id", "po_number", "supplier", "supplier_name", "purchase_request", "pr_number", "status",
                  "status_label", "order_date", "expected_delivery_date", "currency", "notes", "created_by_name",
                  "fully_received_at", "closed_at", "close_reason", "lines", "receipts", "order_total",
                  "received_value", "created_at"]
        read_only_fields = [f for f in fields if f not in ("expected_delivery_date", "notes")]

    def get_order_total(self, obj) -> str:
        return str(sum((l.quantity_ordered * l.unit_price for l in obj.lines.all()), Decimal(0)).quantize(Decimal("0.01")))

    def get_received_value(self, obj) -> str:
        return str(sum((l.quantity_received * l.unit_price for l in obj.lines.all()), Decimal(0)).quantize(Decimal("0.01")))

    def validate(self, attrs):
        if self.instance is not None and self.instance.status not in ("DRAFT", "ISSUED"):
            raise serializers.ValidationError("Only draft or issued orders can be edited.")
        return attrs
