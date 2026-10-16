from __future__ import annotations

from django.contrib.contenttypes.models import ContentType
from rest_framework import serializers

from .models import Attachment, Department, Plant, PlantUnit, SystemSetting
from .settings_registry import SPECS, validate_setting


class PlantSerializer(serializers.ModelSerializer):
    facility_type_label = serializers.CharField(source="get_facility_type_display", read_only=True)

    class Meta:
        model = Plant
        fields = ["id", "code", "name", "facility_type", "facility_type_label", "timezone", "currency", "location",
                  "is_active", "created_at", "updated_at"]


class PlantUnitSerializer(serializers.ModelSerializer):
    plant_code = serializers.CharField(source="plant.code", read_only=True)
    unit_type_label = serializers.CharField(source="get_unit_type_display", read_only=True)

    class Meta:
        model = PlantUnit
        fields = ["id", "plant", "plant_code", "code", "name", "unit_type", "unit_type_label", "description",
                  "requires_shift_reports", "capacity", "capacity_unit", "is_active"]
        validators = [
            serializers.UniqueTogetherValidator(queryset=PlantUnit.objects.all(), fields=["plant", "code"],
                                                message="A unit with this code already exists in the plant.")
        ]


class DepartmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Department
        fields = ["id", "code", "name", "is_active"]


class SystemSettingSerializer(serializers.Serializer):
    key = serializers.CharField(read_only=True)
    value = serializers.JSONField()
    default = serializers.JSONField(read_only=True)
    description = serializers.CharField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True, allow_null=True)

    def validate_value(self, value):
        from django.core.exceptions import ValidationError as DjangoValidationError

        try:
            validate_setting(self.context["key"], value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc
        return value


ATTACHABLE_MODELS = {
    "operationalreport": "operations.operationalreport",
    "equipmentasset": "assets.equipmentasset",
    "workorder": "maintenance.workorder",
    "operationalincident": "operations.operationalincident",
    "operationalexpense": "costs.operationalexpense",
}


class AttachmentSerializer(serializers.ModelSerializer):
    target_type = serializers.ChoiceField(choices=sorted(ATTACHABLE_MODELS), write_only=True)
    uploaded_by_name = serializers.CharField(source="uploaded_by.display_name", read_only=True)
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = Attachment
        fields = ["id", "uuid", "target_type", "object_id", "file", "original_name", "size_bytes", "description",
                  "uploaded_by", "uploaded_by_name", "uploaded_at", "download_url"]
        read_only_fields = ["uuid", "original_name", "size_bytes", "uploaded_by", "uploaded_at"]
        extra_kwargs = {"file": {"write_only": True}}

    def get_download_url(self, obj) -> str:
        return f"/api/core/attachments/{obj.pk}/download/"

    def validate(self, attrs):
        from django.core.exceptions import ValidationError as DjangoValidationError

        from .validators import validate_attachment

        app_label, model = ATTACHABLE_MODELS[attrs.pop("target_type")].split(".")
        ct = ContentType.objects.get(app_label=app_label, model=model)
        if not ct.model_class().objects.filter(pk=attrs["object_id"]).exists():
            raise serializers.ValidationError({"object_id": "The target record does not exist."})
        try:
            validate_attachment(attrs["file"])
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"file": exc.messages}) from exc
        attrs["content_type"] = ct
        attrs["original_name"] = attrs["file"].name[:255]
        attrs["size_bytes"] = attrs["file"].size
        return attrs


def setting_rows() -> list[dict]:
    rows = {s.key: s for s in SystemSetting.objects.all()}
    out = []
    for key, spec in SPECS.items():
        row = rows.get(key)
        out.append({
            "key": key,
            "value": row.value if row else spec.default,
            "default": spec.default,
            "description": spec.description,
            "updated_at": row.updated_at if row else None,
        })
    return out
