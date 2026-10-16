from __future__ import annotations

from rest_framework import serializers

from apps.accounts.serializers import ApprovalRecordSerializer
from apps.assets.models import EquipmentAsset
from apps.core.models import PlantUnit
from apps.workforce.models import ShiftDefinition

from .models import MetricDefinition, OperationalIncident, OperationalMeasurement, OperationalReport, ReportEquipmentStatus


class MetricDefinitionSerializer(serializers.ModelSerializer):
    class Meta:
        model = MetricDefinition
        fields = ["id", "plant", "code", "name", "unit", "description", "aggregation", "direction", "target_value",
                  "valid_min", "valid_max", "alert_low", "alert_high", "is_required", "is_primary_output", "unit_types",
                  "display_order", "is_active"]
        validators = [serializers.UniqueTogetherValidator(queryset=MetricDefinition.objects.all(), fields=["plant", "code"])]

    def validate_unit_types(self, value):
        if not isinstance(value, list) or any(v not in PlantUnit.UnitType.values for v in value):
            raise serializers.ValidationError(f"Use a list of: {', '.join(PlantUnit.UnitType.values)}.")
        return value

    def validate(self, attrs):
        get = lambda k: attrs.get(k, getattr(self.instance, k, None))  # noqa: E731
        if get("valid_min") is not None and get("valid_max") is not None and get("valid_min") > get("valid_max"):
            raise serializers.ValidationError({"valid_max": "Must be greater than or equal to the valid minimum."})
        if get("alert_low") is not None and get("alert_high") is not None and get("alert_low") > get("alert_high"):
            raise serializers.ValidationError({"alert_high": "Must be greater than or equal to the low alert."})
        if get("is_primary_output") and get("is_active"):
            clash = MetricDefinition.objects.filter(plant=get("plant"), is_primary_output=True, is_active=True)
            if self.instance is not None:
                clash = clash.exclude(pk=self.instance.pk)
            if clash.exists():
                raise serializers.ValidationError({"is_primary_output": "The plant already has a primary output metric."})
        return attrs


class MeasurementInputSerializer(serializers.Serializer):
    metric = serializers.PrimaryKeyRelatedField(queryset=MetricDefinition.objects.all())
    value = serializers.DecimalField(max_digits=18, decimal_places=4, allow_null=True, required=False)
    missing_reason = serializers.CharField(max_length=255, allow_blank=True, required=False, default="")
    note = serializers.CharField(max_length=255, allow_blank=True, required=False, default="")


class EquipmentStatusInputSerializer(serializers.Serializer):
    asset = serializers.PrimaryKeyRelatedField(queryset=EquipmentAsset.objects.filter(archived_at__isnull=True))
    status = serializers.ChoiceField(choices=[c for c in EquipmentAsset.Status.values if c != "RETIRED"])
    note = serializers.CharField(max_length=255, allow_blank=True, required=False, default="")


class ReportWriteSerializer(serializers.Serializer):
    plant_unit = serializers.PrimaryKeyRelatedField(queryset=PlantUnit.objects.all(), required=False)
    shift = serializers.PrimaryKeyRelatedField(queryset=ShiftDefinition.objects.all(), required=False)
    report_date = serializers.DateField(required=False)
    summary = serializers.CharField(allow_blank=True, required=False)
    observations = serializers.CharField(allow_blank=True, required=False)
    measurements = MeasurementInputSerializer(many=True, required=False)
    equipment_statuses = EquipmentStatusInputSerializer(many=True, required=False)

    def validate(self, attrs):
        if self.context.get("creating"):
            missing = [f for f in ("plant_unit", "shift", "report_date") if f not in attrs]
            if missing:
                raise serializers.ValidationError({f: "This field is required." for f in missing})
        elif {"plant_unit", "shift", "report_date"} & set(attrs):
            raise serializers.ValidationError("Unit, shift and date cannot be changed after creation.")
        return attrs


class MeasurementSerializer(serializers.ModelSerializer):
    metric_code = serializers.CharField(source="metric.code", read_only=True)
    metric_name = serializers.CharField(source="metric.name", read_only=True)
    unit = serializers.CharField(source="metric.unit", read_only=True)

    class Meta:
        model = OperationalMeasurement
        fields = ["id", "metric", "metric_code", "metric_name", "unit", "value", "missing_reason", "note"]


class EquipmentStatusSerializer(serializers.ModelSerializer):
    asset_tag = serializers.CharField(source="asset.asset_tag", read_only=True)
    asset_name = serializers.CharField(source="asset.name", read_only=True)

    class Meta:
        model = ReportEquipmentStatus
        fields = ["id", "asset", "asset_tag", "asset_name", "status", "note"]


class ReportListSerializer(serializers.ModelSerializer):
    plant_unit_code = serializers.CharField(source="plant_unit.code", read_only=True)
    shift_name = serializers.CharField(source="shift.name", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    created_by_name = serializers.CharField(source="created_by.display_name", read_only=True)
    submitted_by_name = serializers.CharField(source="submitted_by.display_name", read_only=True, default=None)
    reviewed_by_name = serializers.CharField(source="reviewed_by.display_name", read_only=True, default=None)

    class Meta:
        model = OperationalReport
        fields = ["id", "plant_unit", "plant_unit_code", "shift", "shift_name", "report_date", "status", "status_label",
                  "revision", "created_by", "created_by_name", "submitted_by_name", "submitted_at", "reviewed_by_name",
                  "reviewed_at", "updated_at"]


class ReportDetailSerializer(ReportListSerializer):
    measurements = MeasurementSerializer(many=True, read_only=True)
    equipment_statuses = EquipmentStatusSerializer(many=True, read_only=True)
    target_comparison = serializers.SerializerMethodField()
    approvals = serializers.SerializerMethodField()
    incidents = serializers.SerializerMethodField()
    capabilities = serializers.SerializerMethodField()

    class Meta(ReportListSerializer.Meta):
        fields = ReportListSerializer.Meta.fields + [
            "summary", "observations", "review_comment", "measurements", "equipment_statuses", "target_comparison",
            "approvals", "incidents", "capabilities"]

    def get_target_comparison(self, obj):
        from .services import target_comparison

        return target_comparison(obj)

    def get_approvals(self, obj):
        from apps.accounts.audit import approvals_for

        return ApprovalRecordSerializer(approvals_for(obj), many=True).data

    def get_incidents(self, obj):
        return [{"id": i.pk, "incident_number": i.incident_number, "title": i.title, "severity": i.severity,
                 "status": i.status} for i in obj.incidents.all()]

    def get_capabilities(self, obj):
        user = self.context["request"].user
        assigned = user.assigned_units.filter(pk=obj.plant_unit_id).exists()
        prepared = user.pk in (obj.created_by_id, obj.submitted_by_id)
        return {
            "edit": obj.is_editable and user.has_perm_code("opsreports.edit") and assigned,
            "submit": obj.is_editable and user.has_perm_code("opsreports.edit") and assigned,
            "review": obj.status == "SUBMITTED" and user.has_perm_code("opsreports.review") and assigned and not prepared,
            "reopen": obj.status == "APPROVED" and user.has_perm_code("opsreports.reopen") and (
                user.role == "ADMIN" or assigned),
        }


class IncidentSerializer(serializers.ModelSerializer):
    plant_unit_code = serializers.CharField(source="plant_unit.code", read_only=True)
    asset_tag = serializers.CharField(source="asset.asset_tag", read_only=True, default=None)
    reported_by_name = serializers.CharField(source="reported_by.display_name", read_only=True)
    severity_label = serializers.CharField(source="get_severity_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    work_orders = serializers.SerializerMethodField()

    class Meta:
        model = OperationalIncident
        fields = ["id", "incident_number", "plant_unit", "plant_unit_code", "asset", "asset_tag", "report", "occurred_at",
                  "severity", "severity_label", "category", "title", "description", "immediate_action", "status",
                  "status_label", "reported_by", "reported_by_name", "resolved_at", "resolution", "work_orders",
                  "created_at"]
        read_only_fields = ["incident_number", "reported_by", "resolved_at", "resolution"]

    def get_work_orders(self, obj):
        return [{"id": w.pk, "number": w.number, "status": w.status} for w in obj.work_orders.all()]

    def validate_status(self, value):
        if value == OperationalIncident.Status.RESOLVED:
            raise serializers.ValidationError("Use the resolve action to resolve an incident.")
        return value

    def validate(self, attrs):
        if self.instance is not None:
            if self.instance.status == OperationalIncident.Status.RESOLVED:
                raise serializers.ValidationError("Resolved incidents cannot be edited.")
            if {"plant_unit", "occurred_at"} & set(attrs):
                raise serializers.ValidationError("Unit and occurrence time cannot be changed after recording.")
        return attrs
