from __future__ import annotations

from rest_framework import serializers

from .models import EquipmentAsset, EquipmentCategory


class EquipmentCategorySerializer(serializers.ModelSerializer):
    asset_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = EquipmentCategory
        fields = ["id", "code", "name", "description", "is_active", "asset_count"]


class EquipmentAssetSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    plant_unit_code = serializers.CharField(source="plant_unit.code", read_only=True)
    plant_unit_name = serializers.CharField(source="plant_unit.name", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    criticality_label = serializers.CharField(source="get_criticality_display", read_only=True)
    last_maintenance_at = serializers.DateTimeField(read_only=True, allow_null=True)
    next_maintenance_due = serializers.DateField(read_only=True, allow_null=True)
    open_work_orders = serializers.IntegerField(read_only=True)
    is_archived = serializers.BooleanField(read_only=True)

    class Meta:
        model = EquipmentAsset
        fields = [
            "id", "asset_tag", "name", "category", "category_name", "plant_unit", "plant_unit_code", "plant_unit_name",
            "location", "manufacturer", "model_number", "serial_number", "commissioned_on", "status", "status_label",
            "criticality", "criticality_label", "technical_notes", "archived_at", "is_archived",
            "last_maintenance_at", "next_maintenance_due", "open_work_orders", "created_at", "updated_at",
        ]
        read_only_fields = ["archived_at", "created_at", "updated_at"]

    def validate_status(self, value):
        if value == EquipmentAsset.Status.RETIRED:
            raise serializers.ValidationError("Use the archive action to retire an asset.")
        if self.instance is not None and self.instance.is_archived:
            raise serializers.ValidationError("Archived assets cannot change status.")
        return value

    def validate(self, attrs):
        if self.instance is not None and self.instance.is_archived and set(attrs) - {"technical_notes"}:
            raise serializers.ValidationError("Archived assets are read-only except for technical notes.")
        commissioned = attrs.get("commissioned_on")
        if commissioned:
            from django.utils import timezone

            if commissioned > timezone.now().date():
                raise serializers.ValidationError({"commissioned_on": "Commissioning date cannot be in the future."})
        return attrs
