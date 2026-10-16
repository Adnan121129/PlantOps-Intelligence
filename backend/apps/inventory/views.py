from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db.models import F, Q, Sum
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django_filters import rest_framework as filters
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.accounts.permissions import ActionPermission
from apps.core.models import Department
from apps.core.viewsets import AuditedModelViewSet, created

from . import services
from .models import GoodsReceipt, InventoryItem, ItemCategory, PurchaseOrder, PurchaseRequest, StockTransaction, Supplier
from .serializers import (
    GoodsReceiptSerializer,
    InventoryItemSerializer,
    ItemCategorySerializer,
    PurchaseOrderSerializer,
    PurchaseRequestSerializer,
    StockTransactionInputSerializer,
    StockTransactionSerializer,
    SupplierSerializer,
)

TXN_PERMISSION = {"RECEIPT": "stock.receive", "ISSUE": "stock.issue", "RETURN": "stock.return", "ADJUSTMENT": "stock.adjust"}


class ItemCategoryViewSet(AuditedModelViewSet):
    queryset = ItemCategory.objects.all()
    serializer_class = ItemCategorySerializer
    read_permission = "inventory.view"
    action_permissions = {"*": "inventory.manage"}
    pagination_class = None


class SupplierViewSet(AuditedModelViewSet):
    queryset = Supplier.objects.all()
    serializer_class = SupplierSerializer
    read_permission = "inventory.view"
    action_permissions = {"*": "inventory.manage"}
    search_fields = ["code", "name", "contact_name"]
    filterset_fields = ["is_active"]
    http_method_names = ["get", "post", "patch", "head", "options"]


class ItemFilter(filters.FilterSet):
    stock_status = filters.ChoiceFilter(method="filter_stock_status", choices=[
        ("LOW", "At or below reorder point"), ("CRITICAL_LOW", "Critical spares low"), ("OUT_OF_STOCK", "Out of stock"),
        ("OK", "Above reorder point")])
    asset = filters.NumberFilter(field_name="compatible_assets")

    class Meta:
        model = InventoryItem
        fields = ["category", "criticality", "is_active", "preferred_supplier"]

    def filter_stock_status(self, qs, name, value):
        low = Q(current_stock__lte=F("min_stock_level"))
        return {
            "LOW": qs.filter(low),
            "CRITICAL_LOW": qs.filter(low, criticality="CRITICAL"),
            "OUT_OF_STOCK": qs.filter(current_stock__lte=0),
            "OK": qs.exclude(low),
        }[value]


class InventoryItemViewSet(AuditedModelViewSet):
    queryset = InventoryItem.objects.select_related("category", "preferred_supplier").prefetch_related("compatible_assets")
    serializer_class = InventoryItemSerializer
    read_permission = "inventory.view"
    action_permissions = {"*": "inventory.manage", "insight": "inventory.view"}
    filterset_class = ItemFilter
    search_fields = ["item_code", "name", "description", "storage_location"]
    ordering_fields = ["item_code", "name", "current_stock", "last_movement_at"]
    http_method_names = ["get", "post", "patch", "head", "options"]  # deactivate, never delete (ledger history)

    @action(detail=True, methods=["get"])
    def insight(self, request, pk=None):
        item = self.get_object()
        on_order = item.po_lines.filter(order__status__in=["ISSUED", "PARTIALLY_RECEIVED"]).aggregate(
            q=Sum(F("quantity_ordered") - F("quantity_received")))["q"] or Decimal(0)
        since = timezone.now() - dt.timedelta(days=365)
        issued = -(item.transactions.filter(txn_type__in=["ISSUE", "RETURN"], occurred_at__gte=since)
                   .aggregate(q=Sum("quantity"))["q"] or Decimal(0))
        return Response({
            "on_order": str(on_order),
            "issued_last_365d": str(issued),
            "avg_monthly_usage": str((issued / 12).quantize(Decimal("0.001"))),
            "months_of_cover": str((item.current_stock / (issued / 12)).quantize(Decimal("0.1"))) if issued > 0 else None,
            "recent": StockTransactionSerializer(item.transactions.select_related(
                "item", "work_order", "department", "recorded_by")[:15], many=True).data,
            "compatible_assets": [{"id": a.pk, "asset_tag": a.asset_tag, "name": a.name}
                                  for a in item.compatible_assets.all()],
        })


class TxnFilter(filters.FilterSet):
    date_from = filters.DateFilter(method="filter_from")
    date_to = filters.DateFilter(method="filter_to")
    txn_type = filters.MultipleChoiceFilter(choices=StockTransaction.TxnType.choices)

    class Meta:
        model = StockTransaction
        fields = ["item", "work_order", "department", "item__category"]

    def filter_from(self, qs, name, value):
        return qs.filter(occurred_at__gte=dt.datetime.combine(value, dt.time.min, tzinfo=timezone.get_current_timezone()))

    def filter_to(self, qs, name, value):
        return qs.filter(occurred_at__lt=dt.datetime.combine(value + dt.timedelta(days=1), dt.time.min,
                                                             tzinfo=timezone.get_current_timezone()))


class StockTransactionViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """The stock ledger: read-only except for posting new movements. Movements are never edited or deleted."""
    serializer_class = StockTransactionSerializer
    permission_classes = [ActionPermission]
    read_permission = "inventory.view"
    action_permissions = {"create": ("stock.receive", "stock.issue", "stock.return", "stock.adjust")}
    filterset_class = TxnFilter
    search_fields = ["txn_number", "reference", "item__item_code", "item__name", "notes"]
    ordering_fields = ["occurred_at", "txn_number"]

    def get_queryset(self):
        return StockTransaction.objects.select_related("item", "work_order", "department", "recorded_by")

    def create(self, request):
        payload = StockTransactionInputSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        d = payload.validated_data
        if not request.user.has_perm_code(TXN_PERMISSION[d["txn_type"]]):
            raise PermissionDenied(f"Your role cannot record stock {d['txn_type'].lower()}s.")
        if d["txn_type"] == "RECEIPT" and not d.get("reference"):
            raise ValidationError({"reference": "Direct receipts need a reference document (purchase-order receipts "
                                                "are recorded from the purchase order)."})
        result = services.post_transaction(
            item_id=d["item"].pk, txn_type=d["txn_type"], quantity=d["quantity"], user=request.user,
            occurred_at=d.get("occurred_at"), unit_cost=d.get("unit_cost"), work_order=d.get("work_order"),
            department=d.get("department"), reference=d.get("reference", ""), notes=d.get("notes", ""),
            idempotency_key=d.get("idempotency_key"))
        data = StockTransactionSerializer(result.transaction).data
        data["duplicate"] = not result.created
        return Response(data, status=201 if result.created else 200)


class PRFilter(filters.FilterSet):
    status = filters.MultipleChoiceFilter(choices=PurchaseRequest.Status.choices)

    class Meta:
        model = PurchaseRequest
        fields = ["requested_by", "department"]


def _lines(raw) -> list[dict]:
    if not isinstance(raw, list):
        raise ValidationError({"lines": "Provide a list of lines."})
    out = []
    for row in raw:
        try:
            item = InventoryItem.objects.get(pk=int(row.get("item")))
        except (TypeError, ValueError, InventoryItem.DoesNotExist) as exc:
            raise ValidationError({"lines": "Each line needs a valid item."}) from exc
        cost = row.get("estimated_unit_cost")
        try:
            cost = Decimal(str(cost)) if cost not in (None, "") else None
        except InvalidOperation as exc:
            raise ValidationError({"lines": "Invalid estimated unit cost."}) from exc
        if cost is not None and cost < 0:
            raise ValidationError({"lines": "Estimated costs cannot be negative."})
        out.append({"item": item, "quantity": row.get("quantity"), "estimated_unit_cost": cost,
                    "note": str(row.get("note", ""))[:255]})
    return out


def _date(value, field):
    if value in (None, ""):
        return None
    try:
        return dt.date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValidationError({field: "Use the YYYY-MM-DD format."}) from exc


def _department(value):
    if value in (None, ""):
        return None
    dept = Department.objects.filter(pk=value).first()
    if dept is None:
        raise ValidationError({"department": "Unknown department."})
    return dept


class PurchaseRequestViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = PurchaseRequestSerializer
    permission_classes = [ActionPermission]
    read_permission = "procurement.view"
    action_permissions = {"create": "procurement.request", "partial_update": "procurement.request",
                          "submit": "procurement.request", "decide": "procurement.approve",
                          "convert": "procurement.order", "cancel": "procurement.request"}
    filterset_class = PRFilter
    search_fields = ["pr_number", "justification"]
    ordering_fields = ["created_at", "needed_by"]

    def get_queryset(self):
        return PurchaseRequest.objects.select_related("requested_by", "decided_by", "department").prefetch_related(
            "lines__item")

    def _out(self, pr):
        return PurchaseRequestSerializer(self.get_queryset().get(pk=pr.pk)).data

    def create(self, request):
        d = request.data
        pr = services.create_purchase_request(user=request.user, justification=str(d.get("justification", "")).strip()
                                              or _raise("justification", "Explain why the items are needed."),
                                              lines=_lines(d.get("lines", [])), department=_department(d.get("department")),
                                              needed_by=_date(d.get("needed_by"), "needed_by"))
        return created(self._out(pr))

    def partial_update(self, request, pk=None):
        d = request.data
        pr = services.update_purchase_request(
            self.get_object(), user=request.user, justification=d.get("justification"),
            lines=_lines(d["lines"]) if "lines" in d else None, needed_by=_date(d.get("needed_by"), "needed_by"),
            department=_department(d.get("department")))
        return Response(self._out(pr))

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        return Response(self._out(services.submit_purchase_request(self.get_object(), user=request.user)))

    @action(detail=True, methods=["post"])
    def decide(self, request, pk=None):
        decision = request.data.get("decision")
        if decision not in ("approve", "reject"):
            raise ValidationError({"decision": "Use 'approve' or 'reject'."})
        pr = services.decide_purchase_request(self.get_object(), user=request.user, approve=decision == "approve",
                                              comment=str(request.data.get("comment", "")))
        return Response(self._out(pr))

    @action(detail=True, methods=["post"])
    def convert(self, request, pk=None):
        supplier = Supplier.objects.filter(pk=request.data.get("supplier")).first()
        if supplier is None:
            raise ValidationError({"supplier": "Choose a supplier."})
        prices = {}
        for item_id, price in (request.data.get("prices") or {}).items():
            try:
                prices[int(item_id)] = Decimal(str(price))
            except (ValueError, InvalidOperation) as exc:
                raise ValidationError({"prices": "Invalid price."}) from exc
        po = services.convert_to_purchase_order(
            self.get_object(), user=request.user, supplier=supplier, prices=prices,
            expected_delivery_date=_date(request.data.get("expected_delivery_date"), "expected_delivery_date"))
        return created(PurchaseOrderSerializer(po).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        from apps.accounts import audit
        from apps.accounts.models import AuditLog

        pr = self.get_object()
        if pr.requested_by_id != request.user.pk:
            raise ValidationError("Only the requester can cancel this purchase request.")
        if pr.status not in ("DRAFT", "SUBMITTED", "REJECTED"):
            raise ValidationError("This purchase request can no longer be cancelled.")
        before, pr.status = pr.status, PurchaseRequest.Status.CANCELLED
        pr.save(update_fields=["status", "updated_at"])
        audit.record(request.user, AuditLog.Action.STATUS, pr, changes={"status": {"from": before, "to": pr.status}})
        return Response(self._out(pr))


def _raise(field, message):
    raise ValidationError({field: message})


class POFilter(filters.FilterSet):
    status = filters.MultipleChoiceFilter(choices=PurchaseOrder.Status.choices)
    open = filters.BooleanFilter(method="filter_open")

    class Meta:
        model = PurchaseOrder
        fields = ["supplier"]

    def filter_open(self, qs, name, value):
        cond = Q(status__in=["DRAFT", "ISSUED", "PARTIALLY_RECEIVED"])
        return qs.filter(cond) if value else qs.exclude(cond)


class PurchaseOrderViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin,
                           viewsets.GenericViewSet):
    serializer_class = PurchaseOrderSerializer
    permission_classes = [ActionPermission]
    read_permission = "procurement.view"
    action_permissions = {"partial_update": "procurement.order", "issue": "procurement.order",
                          "receive": "stock.receive", "close": "procurement.order", "cancel": "procurement.order"}
    filterset_class = POFilter
    search_fields = ["po_number", "supplier__name", "notes"]
    ordering_fields = ["created_at", "order_date", "expected_delivery_date"]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        return PurchaseOrder.objects.select_related("supplier", "purchase_request", "created_by").prefetch_related(
            "lines__item", "receipts__received_by")

    def _out(self, po):
        return PurchaseOrderSerializer(self.get_queryset().get(pk=po.pk)).data

    def perform_update(self, serializer):
        from apps.accounts import audit
        from apps.accounts.models import AuditLog

        before = audit.snapshot(serializer.instance)
        instance = serializer.save()
        audit.record(self.request.user, AuditLog.Action.UPDATE, instance, changes=audit.diff(before, audit.snapshot(instance)))

    @action(detail=True, methods=["post"])
    def issue(self, request, pk=None):
        po = services.issue_purchase_order(
            self.get_object(), user=request.user, order_date=_date(request.data.get("order_date"), "order_date"),
            expected_delivery_date=_date(request.data.get("expected_delivery_date"), "expected_delivery_date"))
        return Response(self._out(po))

    @action(detail=True, methods=["post"])
    def receive(self, request, pk=None):
        d = request.data
        received_at = parse_datetime(str(d["received_at"])) if d.get("received_at") else None
        if d.get("received_at") and (received_at is None or timezone.is_naive(received_at)):
            raise ValidationError({"received_at": "Enter a date/time with a time-zone offset."})
        lines = [line for line in (d.get("lines") or []) if str(line.get("quantity", "")).strip() not in ("", "0")]
        result = services.receive_goods(self.get_object(), user=request.user, lines=lines, received_at=received_at,
                                        delivery_note=str(d.get("delivery_note", "")), notes=str(d.get("notes", "")),
                                        idempotency_key=d.get("idempotency_key") or None)
        data = self._out(self.get_object())
        data["receipt"] = {"id": result.receipt.pk, "receipt_number": result.receipt.receipt_number,
                           "duplicate": not result.created}
        return Response(data, status=201 if result.created else 200)

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        return Response(self._out(services.close_purchase_order(self.get_object(), user=request.user,
                                                                reason=str(request.data.get("reason", "")))))

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        return Response(self._out(services.cancel_purchase_order(self.get_object(), user=request.user,
                                                                 reason=str(request.data.get("reason", "")))))


class GoodsReceiptViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = GoodsReceipt.objects.select_related("order", "received_by")
    serializer_class = GoodsReceiptSerializer
    permission_classes = [ActionPermission]
    read_permission = "procurement.view"
    filterset_fields = ["order"]
