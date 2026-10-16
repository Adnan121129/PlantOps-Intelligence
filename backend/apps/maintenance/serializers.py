from __future__ import annotations

import datetime as dt

from django.utils import timezone
from rest_framework import serializers

from apps.accounts.serializers import ApprovalRecordSerializer
from apps.assets.models import EquipmentAsset
from apps.core.settings_registry import get_setting
from apps.operations.models import OperationalIncident
from apps.workforce.models import Employee

from .models import DowntimeEvent, InspectionRecord, MaintenanceSchedule, WorkOrder


def is_overdue(wo: WorkOrder, *, now: dt.datetime, today: dt.date, grace: int) -> bool:
    if not wo.is_open:
        return False
    if wo.schedule_id:
        return wo.due_date is not None and wo.due_date < today - dt.timedelta(days=grace)
    return wo.planned_end is not None and wo.planned_end < now


class OverdueMixin:
    def _overdue(self, obj) -> bool:
        ctx = self.context
        if "_grace" not in ctx:
            ctx["_grace"] = get_setting("pm_compliance_grace_days")
            ctx["_now"] = timezone.now()
            ctx["_today"] = timezone.localdate()
        return is_overdue(obj, now=ctx["_now"], today=ctx["_today"], grace=ctx["_grace"])


class WorkOrderListSerializer(OverdueMixin, serializers.ModelSerializer):
    asset_tag = serializers.CharField(source="asset.asset_tag", read_only=True)
    asset_name = serializers.CharField(source="asset.name", read_only=True)
    plant_unit_code = serializers.CharField(source="asset.plant_unit.code", read_only=True)
    technician_name = serializers.CharField(source="assigned_technician.full_name", read_only=True, default=None)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    maintenance_type_label = serializers.CharField(source="get_maintenance_type_display", read_only=True)
    is_overdue = serializers.SerializerMethodField()
    downtime_hours = serializers.SerializerMethodField()

    class Meta:
        model = WorkOrder
        fields = ["id", "number", "asset", "asset_tag", "asset_name", "plant_unit_code", "maintenance_type",
                  "maintenance_type_label", "title", "priority", "status", "status_label", "is_overdue", "is_blocked",
                  "blocked_reason", "assigned_technician", "technician_name", "assigned_team", "due_date",
                  "planned_start", "planned_end", "reported_at", "actual_start", "actual_end", "schedule",
                  "downtime_hours"]

    def get_is_overdue(self, obj) -> bool:
        return self._overdue(obj)

    def get_downtime_hours(self, obj) -> float | None:
        events = list(obj.downtime_events.all())
        if not events:
            return 0.0
        now = timezone.now()
        return round(sum(((e.ended_at or now) - e.started_at).total_seconds() for e in events) / 3600, 2)


class WorkOrderDetailSerializer(WorkOrderListSerializer):
    reported_by_name = serializers.CharField(source="reported_by.display_name", read_only=True)
    completed_by_name = serializers.CharField(source="completed_by.display_name", read_only=True, default=None)
    verified_by_name = serializers.CharField(source="verified_by.display_name", read_only=True, default=None)
    cancelled_by_name = serializers.CharField(source="cancelled_by.display_name", read_only=True, default=None)
    incident_number = serializers.CharField(source="incident.incident_number", read_only=True, default=None)
    downtime_events = serializers.SerializerMethodField()
    parts = serializers.SerializerMethodField()
    costs = serializers.SerializerMethodField()
    expenses = serializers.SerializerMethodField()
    inspections = serializers.SerializerMethodField()
    approvals = serializers.SerializerMethodField()
    capabilities = serializers.SerializerMethodField()

    class Meta(WorkOrderListSerializer.Meta):
        fields = WorkOrderListSerializer.Meta.fields + [
            "description", "incident", "incident_number", "reported_by", "reported_by_name", "failure_code",
            "root_cause", "actions_performed", "completion_notes", "labor_hours", "requires_verification",
            "completed_by_name", "verified_by_name", "verified_at", "verification_comment", "cancelled_reason",
            "cancelled_by_name", "cancelled_at", "downtime_events", "parts", "costs", "expenses", "inspections",
            "approvals", "capabilities", "created_at", "updated_at"]

    def get_downtime_events(self, obj):
        return DowntimeEventSerializer(obj.downtime_events.all(), many=True, context=self.context).data

    def get_parts(self, obj):
        rows = []
        for t in obj.stock_transactions.select_related("item").order_by("occurred_at"):
            rows.append({"id": t.pk, "txn_number": t.txn_number, "txn_type": t.txn_type, "item": t.item_id,
                         "item_code": t.item.item_code, "item_name": t.item.name, "uom": t.item.uom,
                         "quantity": str(-t.quantity), "unit_cost": str(t.unit_cost), "value": str(-t.total_value),
                         "occurred_at": t.occurred_at})
        return rows

    def get_costs(self, obj):
        from apps.analytics.services import work_order_costs

        return work_order_costs(obj)

    def get_expenses(self, obj):
        if not self.context["request"].user.has_perm_code("costs.view"):
            return None
        return [{"id": e.pk, "expense_date": e.expense_date, "category": e.category, "amount": str(e.amount),
                 "description": e.description, "source": e.source, "reference": e.reference}
                for e in obj.expenses.filter(cost_type="ACTUAL").order_by("expense_date", "id")]

    def get_inspections(self, obj):
        return InspectionSerializer(obj.inspections.all(), many=True).data

    def get_approvals(self, obj):
        from apps.accounts.audit import approvals_for

        return ApprovalRecordSerializer(approvals_for(obj), many=True).data

    def get_capabilities(self, obj):
        user = self.context["request"].user
        manage = user.has_perm_code("workorders.manage")
        s = WorkOrder.Status
        return {
            "edit": obj.is_open and manage,
            "assign": obj.status in (s.REPORTED, s.ASSIGNED, s.IN_PROGRESS) and manage,
            "start": obj.status == s.ASSIGNED and manage,
            "complete": obj.status == s.IN_PROGRESS and manage,
            "verify": obj.status == s.AWAITING_VERIFICATION and user.has_perm_code("workorders.verify")
                      and obj.completed_by_id != user.pk,
            "cancel": obj.is_open and user.has_perm_code("workorders.cancel"),
            "block": obj.is_open and manage,
            "add_cost": obj.status != s.CANCELLED and manage,
            "issue_parts": obj.status in (s.ASSIGNED, s.IN_PROGRESS) and user.has_perm_code("stock.issue"),
            "return_parts": obj.status != s.CANCELLED and user.has_perm_code("stock.return"),
            "record_downtime": obj.status != s.CANCELLED and user.has_perm_code("downtime.record"),
        }


class WorkOrderCreateSerializer(serializers.Serializer):
    asset = serializers.PrimaryKeyRelatedField(queryset=EquipmentAsset.objects.all())
    maintenance_type = serializers.ChoiceField(choices=WorkOrder.MaintenanceType.choices,
                                               default=WorkOrder.MaintenanceType.CORRECTIVE)
    title = serializers.CharField(max_length=200)
    description = serializers.CharField()
    priority = serializers.ChoiceField(choices=WorkOrder.Priority.choices, default=WorkOrder.Priority.MEDIUM)
    reported_at = serializers.DateTimeField(required=False)
    incident = serializers.PrimaryKeyRelatedField(queryset=OperationalIncident.objects.all(), required=False, allow_null=True)
    requires_verification = serializers.BooleanField(required=False, allow_null=True, default=None)
    planned_start = serializers.DateTimeField(required=False, allow_null=True)
    planned_end = serializers.DateTimeField(required=False, allow_null=True)
    assigned_technician = serializers.PrimaryKeyRelatedField(queryset=Employee.objects.all(), required=False, allow_null=True)
    assigned_team = serializers.CharField(max_length=80, required=False, allow_blank=True)


class WorkOrderUpdateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200, required=False)
    description = serializers.CharField(required=False)
    priority = serializers.ChoiceField(choices=WorkOrder.Priority.choices, required=False)
    planned_start = serializers.DateTimeField(required=False, allow_null=True)
    planned_end = serializers.DateTimeField(required=False, allow_null=True)
    assigned_team = serializers.CharField(max_length=80, required=False, allow_blank=True)
    requires_verification = serializers.BooleanField(required=False)
    root_cause = serializers.CharField(required=False, allow_blank=True)
    failure_code = serializers.ChoiceField(choices=WorkOrder.FailureCode.choices, required=False, allow_blank=True)


class DowntimeEventSerializer(serializers.ModelSerializer):
    asset_tag = serializers.CharField(source="asset.asset_tag", read_only=True)
    asset_name = serializers.CharField(source="asset.name", read_only=True)
    plant_unit_code = serializers.CharField(source="asset.plant_unit.code", read_only=True)
    category_name = serializers.CharField(source="asset.category.name", read_only=True)
    work_order_number = serializers.CharField(source="work_order.number", read_only=True, default=None)
    downtime_type_label = serializers.CharField(source="get_downtime_type_display", read_only=True)
    duration_hours = serializers.FloatField(read_only=True)
    is_ongoing = serializers.BooleanField(read_only=True)
    recorded_by_name = serializers.CharField(source="recorded_by.display_name", read_only=True)

    class Meta:
        model = DowntimeEvent
        fields = ["id", "asset", "asset_tag", "asset_name", "plant_unit_code", "category_name", "work_order",
                  "work_order_number", "incident", "downtime_type", "downtime_type_label", "started_at", "ended_at",
                  "duration_hours", "is_ongoing", "cause", "description", "recorded_by_name", "created_at"]
        # Overlap/ordering checks run in the service layer with row locks.
        validators = []


class InspectionSerializer(serializers.ModelSerializer):
    inspector_name = serializers.CharField(source="inspector.display_name", read_only=True)
    asset_tag = serializers.CharField(source="asset.asset_tag", read_only=True)
    work_order_number = serializers.CharField(source="work_order.number", read_only=True, default=None)

    class Meta:
        model = InspectionRecord
        fields = ["id", "asset", "asset_tag", "work_order", "work_order_number", "inspected_at", "inspector",
                  "inspector_name", "result", "findings", "readings", "follow_up_work_order"]
        read_only_fields = ["inspector"]

    def validate(self, attrs):
        if attrs.get("inspected_at") and attrs["inspected_at"] > timezone.now() + dt.timedelta(minutes=5):
            raise serializers.ValidationError({"inspected_at": "Inspections cannot be dated in the future."})
        wo = attrs.get("work_order")
        if wo is not None and wo.asset_id != attrs["asset"].pk:
            raise serializers.ValidationError({"work_order": "The work order is for a different asset."})
        if attrs.get("result") in ("FAIL", "ATTENTION") and not attrs.get("findings", "").strip():
            raise serializers.ValidationError({"findings": "Describe the findings."})
        return attrs


class ScheduleSerializer(serializers.ModelSerializer):
    asset_tag = serializers.CharField(source="asset.asset_tag", read_only=True)
    asset_name = serializers.CharField(source="asset.name", read_only=True)
    technician_name = serializers.CharField(source="default_technician.full_name", read_only=True, default=None)
    next_due_date = serializers.SerializerMethodField()
    last_completed_at = serializers.DateTimeField(read_only=True, allow_null=True)
    open_work_orders = serializers.IntegerField(read_only=True)

    class Meta:
        model = MaintenanceSchedule
        fields = ["id", "asset", "asset_tag", "asset_name", "title", "description", "task_type", "interval_days",
                  "start_date", "lead_days", "reminder_days", "estimated_hours", "default_technician",
                  "technician_name", "priority", "is_active", "last_generated_due_date", "next_due_date",
                  "last_completed_at", "open_work_orders"]
        read_only_fields = ["last_generated_due_date"]

    def get_next_due_date(self, obj):
        open_due = obj.work_orders.filter(status__in=WorkOrder.OPEN_STATUSES).order_by("due_date").values_list(
            "due_date", flat=True).first()
        return (open_due or obj.next_generation_due_date).isoformat()

    def validate_priority(self, value):
        if value not in WorkOrder.Priority.values:
            raise serializers.ValidationError("Invalid priority.")
        return value

    def validate(self, attrs):
        from .services import validate_schedule_start

        if self.instance is not None and self.instance.last_generated_due_date and (
                "start_date" in attrs or "interval_days" in attrs):
            if attrs.get("start_date", self.instance.start_date) != self.instance.start_date or attrs.get(
                    "interval_days", self.instance.interval_days) != self.instance.interval_days:
                raise serializers.ValidationError(
                    "The interval and start date are fixed once work orders have been generated; deactivate this "
                    "schedule and create a new one to change the plan.")
        if self.instance is None:
            validate_schedule_start(attrs["start_date"], attrs["interval_days"], timezone.localdate())
            if attrs["asset"].is_archived:
                raise serializers.ValidationError({"asset": "The asset is archived."})
        lead = attrs.get("lead_days", getattr(self.instance, "lead_days", 7))
        interval = attrs.get("interval_days", getattr(self.instance, "interval_days", 1))
        if lead >= interval:
            raise serializers.ValidationError({"lead_days": "Lead time must be shorter than the interval."})
        return attrs
