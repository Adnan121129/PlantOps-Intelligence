from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db.models import Count, Max, Prefetch, Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django_filters import rest_framework as filters
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.permissions import ActionPermission
from apps.analytics.services import overdue_q
from apps.core.viewsets import AuditedModelViewSet, created
from apps.inventory.models import InventoryItem, StockTransaction
from apps.inventory.services import post_transaction
from apps.workforce.models import Employee

from . import services
from .models import DowntimeEvent, InspectionRecord, MaintenanceSchedule, WorkOrder
from .serializers import (
    DowntimeEventSerializer,
    InspectionSerializer,
    ScheduleSerializer,
    WorkOrderCreateSerializer,
    WorkOrderDetailSerializer,
    WorkOrderListSerializer,
    WorkOrderUpdateSerializer,
)


def _dt(value, field: str, required: bool = False):
    if value in (None, ""):
        if required:
            raise ValidationError({field: "This field is required."})
        return None
    parsed = parse_datetime(str(value))
    if parsed is None:
        raise ValidationError({field: "Enter a valid date/time."})
    if timezone.is_naive(parsed):
        raise ValidationError({field: "Include a time-zone offset."})
    return parsed


def _decimal(value, field: str, required: bool = False):
    if value in (None, ""):
        if required:
            raise ValidationError({field: "This field is required."})
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise ValidationError({field: "Enter a valid number."}) from exc


class WorkOrderFilter(filters.FilterSet):
    status = filters.MultipleChoiceFilter(choices=WorkOrder.Status.choices)
    open = filters.BooleanFilter(method="filter_open")
    overdue = filters.BooleanFilter(method="filter_overdue")
    reported_from = filters.DateFilter(method="filter_reported_from")
    reported_to = filters.DateFilter(method="filter_reported_to")
    due_from = filters.DateFilter(field_name="due_date", lookup_expr="gte")
    due_to = filters.DateFilter(field_name="due_date", lookup_expr="lte")
    unit = filters.NumberFilter(field_name="asset__plant_unit")
    plant = filters.NumberFilter(field_name="asset__plant_unit__plant")
    category = filters.NumberFilter(field_name="asset__category")
    preventive = filters.BooleanFilter(field_name="schedule", lookup_expr="isnull", exclude=True)

    class Meta:
        model = WorkOrder
        fields = ["asset", "maintenance_type", "priority", "assigned_technician", "is_blocked", "schedule", "incident"]

    def filter_open(self, qs, name, value):
        return qs.filter(status__in=WorkOrder.OPEN_STATUSES) if value else qs.filter(status__in=WorkOrder.CLOSED_STATUSES)

    def filter_overdue(self, qs, name, value):
        cond = overdue_q(timezone.now(), timezone.localdate())
        return qs.filter(cond) if value else qs.exclude(cond)

    # Date filters are local business dates; converted with the server's current time zone.
    def filter_reported_from(self, qs, name, value):
        return qs.filter(reported_at__gte=dt.datetime.combine(value, dt.time.min, tzinfo=timezone.get_current_timezone()))

    def filter_reported_to(self, qs, name, value):
        end = dt.datetime.combine(value + dt.timedelta(days=1), dt.time.min, tzinfo=timezone.get_current_timezone())
        return qs.filter(reported_at__lt=end)


class WorkOrderViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [ActionPermission]
    read_permission = "workorders.view"
    action_permissions = {
        "create": "workorders.report", "partial_update": "workorders.manage", "assign": "workorders.manage",
        "start": "workorders.manage", "complete": "workorders.manage", "verify": "workorders.verify",
        "cancel": "workorders.cancel", "block": "workorders.manage", "add_cost": "workorders.manage",
        "issue_part": "stock.issue", "return_part": "stock.return",
    }
    filterset_class = WorkOrderFilter
    search_fields = ["number", "title", "description", "asset__asset_tag", "asset__name"]
    ordering_fields = ["reported_at", "priority", "status", "due_date", "planned_end", "number"]

    def get_queryset(self):
        return WorkOrder.objects.select_related(
            "asset", "asset__plant_unit", "assigned_technician", "reported_by", "completed_by", "verified_by",
            "cancelled_by", "incident").prefetch_related(Prefetch("downtime_events"))

    def get_serializer_class(self):
        return WorkOrderDetailSerializer if self.action != "list" else WorkOrderListSerializer

    def _detail(self, wo):
        return WorkOrderDetailSerializer(self.get_queryset().get(pk=wo.pk), context=self.get_serializer_context()).data

    def create(self, request):
        payload = WorkOrderCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        wo = services.create_work_order(user=request.user, **payload.validated_data)
        return created(self._detail(wo))

    def partial_update(self, request, pk=None):
        payload = WorkOrderUpdateSerializer(data=request.data, partial=True)
        payload.is_valid(raise_exception=True)
        return Response(self._detail(services.update_details(self.get_object(), user=request.user,
                                                             data=payload.validated_data)))

    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        tech_id = request.data.get("assigned_technician")
        technician = Employee.objects.filter(pk=tech_id).first() if tech_id else None
        if tech_id and technician is None:
            raise ValidationError({"assigned_technician": "Unknown employee."})
        wo = services.assign(self.get_object(), user=request.user, technician=technician,
                             team=str(request.data.get("assigned_team", "")),
                             planned_start=_dt(request.data.get("planned_start"), "planned_start"),
                             planned_end=_dt(request.data.get("planned_end"), "planned_end"))
        return Response(self._detail(wo))

    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        wo = services.start(self.get_object(), user=request.user,
                            actual_start=_dt(request.data.get("actual_start"), "actual_start"))
        return Response(self._detail(wo))

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        d = request.data
        failure_code = str(d.get("failure_code", ""))
        if failure_code and failure_code not in WorkOrder.FailureCode.values:
            raise ValidationError({"failure_code": "Unknown failure code."})
        wo = services.complete(
            self.get_object(), user=request.user, actions_performed=str(d.get("actions_performed", "")),
            actual_end=_dt(d.get("actual_end"), "actual_end"), failure_code=failure_code,
            root_cause=str(d.get("root_cause", "")), labor_hours=_decimal(d.get("labor_hours"), "labor_hours"),
            completion_notes=str(d.get("completion_notes", "")))
        return Response(self._detail(wo))

    @action(detail=True, methods=["post"])
    def verify(self, request, pk=None):
        decision = request.data.get("decision")
        if decision not in ("approve", "return"):
            raise ValidationError({"decision": "Use 'approve' or 'return'."})
        wo = services.verify(self.get_object(), user=request.user, approve=decision == "approve",
                             comment=str(request.data.get("comment", "")))
        return Response(self._detail(wo))

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        return Response(self._detail(services.cancel(self.get_object(), user=request.user,
                                                     reason=str(request.data.get("reason", "")))))

    @action(detail=True, methods=["post"])
    def block(self, request, pk=None):
        wo = services.set_blocked(self.get_object(), user=request.user, blocked=bool(request.data.get("blocked")),
                                  reason=str(request.data.get("reason", "")))
        return Response(self._detail(wo))

    @action(detail=True, methods=["post"], url_path="costs")
    def add_cost(self, request, pk=None):
        d = request.data
        expense_date = d.get("expense_date")
        try:
            expense_date = dt.date.fromisoformat(expense_date) if expense_date else None
        except ValueError as exc:
            raise ValidationError({"expense_date": "Use the YYYY-MM-DD format."}) from exc
        services.add_cost(self.get_object(), user=request.user, category=str(d.get("category", "")),
                          amount=_decimal(d.get("amount"), "amount", required=True),
                          description=str(d.get("description", "")) or "Work order cost",
                          expense_date=expense_date, reference=str(d.get("reference", "")))
        return created(self._detail(self.get_object()))

    def _stock(self, request, txn_type: str):
        wo = self.get_object()
        d = request.data
        item_id = d.get("item")
        if not str(item_id or "").isdigit() or not InventoryItem.objects.filter(pk=item_id).exists():
            raise ValidationError({"item": "Choose an inventory item."})
        result = post_transaction(
            item_id=int(item_id), txn_type=txn_type, quantity=d.get("quantity"), user=request.user, work_order=wo,
            notes=str(d.get("notes", "")), idempotency_key=d.get("idempotency_key") or None,
            reference=wo.number)
        data = self._detail(wo)
        data["posted_transaction"] = {"id": result.transaction.pk, "txn_number": result.transaction.txn_number,
                                      "duplicate": not result.created}
        return Response(data, status=201 if result.created else 200)

    @action(detail=True, methods=["post"], url_path="issue-part")
    def issue_part(self, request, pk=None):
        return self._stock(request, StockTransaction.TxnType.ISSUE)

    @action(detail=True, methods=["post"], url_path="return-part")
    def return_part(self, request, pk=None):
        return self._stock(request, StockTransaction.TxnType.RETURN)


class DowntimeFilter(filters.FilterSet):
    date_from = filters.DateFilter(method="filter_from")
    date_to = filters.DateFilter(method="filter_to")
    ongoing = filters.BooleanFilter(field_name="ended_at", lookup_expr="isnull")
    unit = filters.NumberFilter(field_name="asset__plant_unit")
    category = filters.NumberFilter(field_name="asset__category")
    downtime_type = filters.MultipleChoiceFilter(choices=DowntimeEvent.DowntimeType.choices)

    class Meta:
        model = DowntimeEvent
        fields = ["asset", "work_order", "incident"]

    # Range filters select events *overlapping* the range, consistent with downtime KPIs.
    def filter_from(self, qs, name, value):
        start = dt.datetime.combine(value, dt.time.min, tzinfo=timezone.get_current_timezone())
        return qs.filter(Q(ended_at__isnull=True) | Q(ended_at__gt=start))

    def filter_to(self, qs, name, value):
        end = dt.datetime.combine(value + dt.timedelta(days=1), dt.time.min, tzinfo=timezone.get_current_timezone())
        return qs.filter(started_at__lt=end)


class DowntimeViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = DowntimeEventSerializer
    permission_classes = [ActionPermission]
    read_permission = "assets.view"
    action_permissions = {"create": "downtime.record", "partial_update": "downtime.record", "close": "downtime.record"}
    filterset_class = DowntimeFilter
    search_fields = ["cause", "description", "asset__asset_tag", "asset__name"]
    ordering_fields = ["started_at", "ended_at"]

    def get_queryset(self):
        return DowntimeEvent.objects.select_related("asset", "asset__plant_unit", "asset__category", "work_order",
                                                    "recorded_by")

    def create(self, request):
        s = DowntimeEventSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        event = services.record_downtime(
            user=request.user, asset=d["asset"], downtime_type=d["downtime_type"], started_at=d["started_at"],
            ended_at=d.get("ended_at"), cause=d["cause"], description=d.get("description", ""),
            work_order=d.get("work_order"), incident=d.get("incident"))
        return created(DowntimeEventSerializer(self.get_queryset().get(pk=event.pk)).data)

    def partial_update(self, request, pk=None):
        event = self.get_object()
        s = DowntimeEventSerializer(event, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        data = {k: v for k, v in s.validated_data.items() if k != "asset"}
        if "asset" in s.validated_data and s.validated_data["asset"].pk != event.asset_id:
            raise ValidationError({"asset": "The asset of a downtime event cannot be changed."})
        event = services.update_downtime(event, user=request.user, data=data)
        return Response(DowntimeEventSerializer(self.get_queryset().get(pk=event.pk)).data)

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        event = services.close_downtime(self.get_object(), user=request.user,
                                        ended_at=_dt(request.data.get("ended_at"), "ended_at"))
        return Response(DowntimeEventSerializer(self.get_queryset().get(pk=event.pk)).data)


class ScheduleViewSet(AuditedModelViewSet):
    serializer_class = ScheduleSerializer
    read_permission = "workorders.view"
    action_permissions = {"*": "pm.manage", "calendar": "workorders.view"}
    filterset_fields = ["asset", "task_type", "is_active", "asset__plant_unit"]
    search_fields = ["title", "asset__asset_tag", "asset__name"]
    http_method_names = ["get", "post", "patch", "head", "options"]  # deactivate instead of delete

    def get_queryset(self):
        return MaintenanceSchedule.objects.select_related("asset", "default_technician").annotate(
            last_completed_at=Max("work_orders__actual_end", filter=Q(work_orders__status="COMPLETED")),
            open_work_orders=Count("work_orders", filter=Q(work_orders__status__in=WorkOrder.OPEN_STATUSES)),
        ).order_by("asset__asset_tag", "title")

    def get_create_kwargs(self):
        return {"created_by": self.request.user}

    @action(detail=False, methods=["post"])
    def generate(self, request):
        created_wos = services.generate_pm_work_orders(user=request.user)
        return Response({"created": len(created_wos), "work_orders": [w.number for w in created_wos]})

    @action(detail=False, methods=["get"])
    def calendar(self, request):
        try:
            start = dt.date.fromisoformat(request.query_params.get("start") or timezone.localdate().replace(day=1).isoformat())
            end = dt.date.fromisoformat(request.query_params.get("end") or (start + dt.timedelta(days=41)).isoformat())
        except ValueError as exc:
            raise ValidationError({"start": "Use the YYYY-MM-DD format."}) from exc
        if end < start or (end - start).days > 120:
            raise ValidationError({"end": "Choose a range of at most 120 days."})
        unit = request.query_params.get("unit")
        return Response({"start": start, "end": end, "entries": services.pm_calendar(
            start, end, unit_id=int(unit) if unit and unit.isdigit() else None)})


class InspectionViewSet(AuditedModelViewSet):
    queryset = InspectionRecord.objects.select_related("asset", "inspector", "work_order")
    serializer_class = InspectionSerializer
    read_permission = "workorders.view"
    action_permissions = {"create": "workorders.manage"}
    filterset_fields = ["asset", "work_order", "result"]
    http_method_names = ["get", "post", "head", "options"]  # inspection records are immutable

    def get_create_kwargs(self):
        return {"inspector": self.request.user}
