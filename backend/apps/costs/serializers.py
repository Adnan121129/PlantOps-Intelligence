from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework import serializers

from apps.core.settings_registry import get_setting

from .models import Budget, CostCategory, OperationalExpense
from .services import validate_currency, validate_expense_amount


def _wrap(fn, *args):
    try:
        fn(*args)
    except DjangoValidationError as exc:
        raise serializers.ValidationError(exc.message_dict if hasattr(exc, "error_dict") else exc.messages) from exc


class ExpenseSerializer(serializers.ModelSerializer):
    category_label = serializers.CharField(source="get_category_display", read_only=True)
    cost_type_label = serializers.CharField(source="get_cost_type_display", read_only=True)
    source_label = serializers.CharField(source="get_source_display", read_only=True)
    asset_tag = serializers.CharField(source="asset.asset_tag", read_only=True, default=None)
    work_order_number = serializers.CharField(source="work_order.number", read_only=True, default=None)
    department_name = serializers.CharField(source="department.name", read_only=True, default=None)
    plant_unit_code = serializers.CharField(source="plant_unit.code", read_only=True, default=None)
    recorded_by_name = serializers.CharField(source="recorded_by.display_name", read_only=True)
    currency = serializers.CharField(max_length=3, required=False)

    class Meta:
        model = OperationalExpense
        fields = ["id", "expense_date", "category", "category_label", "cost_type", "cost_type_label", "amount",
                  "currency", "description", "reference", "asset", "asset_tag", "work_order", "work_order_number",
                  "department", "department_name", "plant_unit", "plant_unit_code", "source", "source_label",
                  "recorded_by", "recorded_by_name", "created_at"]
        read_only_fields = ["source", "recorded_by", "work_order"]

    def validate(self, attrs):
        if self.instance is not None and self.instance.source != OperationalExpense.Source.MANUAL:
            raise serializers.ValidationError("System-generated cost entries cannot be edited; correct the source record.")
        attrs.setdefault("currency", getattr(self.instance, "currency", None) or get_setting("base_currency"))
        _wrap(validate_currency, attrs["currency"])
        if "amount" in attrs:
            _wrap(validate_expense_amount, attrs["amount"])
        cost_type = attrs.get("cost_type", getattr(self.instance, "cost_type", "ACTUAL"))
        date = attrs.get("expense_date", getattr(self.instance, "expense_date", None))
        if cost_type == "ACTUAL" and date and date > timezone.localdate():
            raise serializers.ValidationError({"expense_date": "Actual costs cannot be dated in the future."})
        asset, unit = attrs.get("asset"), attrs.get("plant_unit")
        if asset is not None:
            if unit is not None and unit.pk != asset.plant_unit_id:
                raise serializers.ValidationError({"plant_unit": "The asset belongs to a different unit."})
            attrs["plant_unit"] = asset.plant_unit
        if attrs.get("category") == CostCategory.SPARE_PARTS and asset is not None:
            raise serializers.ValidationError({"category": "Spare parts for equipment are costed when issued from stock "
                                                           "against a work order. Record only non-stock purchases here."})
        return attrs


class BudgetSerializer(serializers.ModelSerializer):
    category_label = serializers.CharField(source="get_category_display", read_only=True)
    department_name = serializers.CharField(source="department.name", read_only=True, default=None)
    currency = serializers.CharField(max_length=3, required=False)

    class Meta:
        model = Budget
        fields = ["id", "year", "month", "department", "department_name", "category", "category_label", "amount",
                  "currency", "notes"]
        validators = []

    def validate(self, attrs):
        attrs.setdefault("currency", getattr(self.instance, "currency", None) or get_setting("base_currency"))
        _wrap(validate_currency, attrs["currency"])
        if not 1 <= attrs.get("month", getattr(self.instance, "month", 1)) <= 12:
            raise serializers.ValidationError({"month": "Month must be between 1 and 12."})
        if attrs.get("amount") is not None and attrs["amount"] < 0:
            raise serializers.ValidationError({"amount": "Budgets cannot be negative."})
        key = {k: attrs.get(k, getattr(self.instance, k, None)) for k in ("year", "month", "department", "category")}
        clash = Budget.objects.filter(**key)
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError("A budget line already exists for this month, department and category.")
        return attrs
