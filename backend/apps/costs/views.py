from __future__ import annotations

from django_filters import rest_framework as filters
from rest_framework.exceptions import ValidationError

from apps.core.viewsets import AuditedModelViewSet

from .models import Budget, OperationalExpense
from .serializers import BudgetSerializer, ExpenseSerializer


class ExpenseFilter(filters.FilterSet):
    date_from = filters.DateFilter(field_name="expense_date", lookup_expr="gte")
    date_to = filters.DateFilter(field_name="expense_date", lookup_expr="lte")
    category = filters.MultipleChoiceFilter(choices=OperationalExpense._meta.get_field("category").choices)
    unit = filters.NumberFilter(method="filter_unit")
    maintenance = filters.BooleanFilter(method="filter_maintenance")
    min_amount = filters.NumberFilter(field_name="amount", lookup_expr="gte")

    class Meta:
        model = OperationalExpense
        fields = ["id", "cost_type", "source", "asset", "work_order", "department"]

    def filter_unit(self, qs, name, value):
        from django.db.models import Q

        return qs.filter(Q(plant_unit_id=value) | Q(asset__plant_unit_id=value))

    def filter_maintenance(self, qs, name, value):
        from django.db.models import Q

        cond = Q(work_order__isnull=False) | Q(asset__isnull=False)
        return qs.filter(cond) if value else qs.exclude(cond)


class ExpenseViewSet(AuditedModelViewSet):
    serializer_class = ExpenseSerializer
    read_permission = "costs.view"
    action_permissions = {"*": "costs.record"}
    filterset_class = ExpenseFilter
    search_fields = ["description", "reference", "asset__asset_tag", "work_order__number"]
    ordering_fields = ["expense_date", "amount", "category"]

    def get_queryset(self):
        return OperationalExpense.objects.select_related("asset", "work_order", "department", "plant_unit", "recorded_by")

    def get_create_kwargs(self):
        return {"recorded_by": self.request.user, "source": OperationalExpense.Source.MANUAL}

    def perform_destroy(self, instance):
        if instance.source != OperationalExpense.Source.MANUAL:
            raise ValidationError("System-generated cost entries cannot be deleted; reverse the source record instead.")
        super().perform_destroy(instance)


class BudgetViewSet(AuditedModelViewSet):
    queryset = Budget.objects.select_related("department")
    serializer_class = BudgetSerializer
    read_permission = "costs.view"
    action_permissions = {"*": "budgets.manage"}
    filterset_fields = ["year", "month", "department", "category"]
    ordering_fields = ["year", "month", "category"]
