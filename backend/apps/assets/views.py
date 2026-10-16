from __future__ import annotations

from django.db import transaction
from django.db.models import Count, Max, OuterRef, Q, Subquery
from django.utils import timezone
from django_filters import rest_framework as filters
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts import audit
from apps.accounts.models import AuditLog
from apps.core.viewsets import AuditedModelViewSet

from .models import EquipmentAsset, EquipmentCategory
from .serializers import EquipmentAssetSerializer, EquipmentCategorySerializer


class EquipmentCategoryViewSet(AuditedModelViewSet):
    queryset = EquipmentCategory.objects.annotate(asset_count=Count("assets"))
    serializer_class = EquipmentCategorySerializer
    action_permissions = {"*": "reference.manage", "list": "assets.view", "retrieve": "assets.view"}
    search_fields = ["code", "name"]
    pagination_class = None


class AssetFilter(filters.FilterSet):
    plant = filters.NumberFilter(field_name="plant_unit__plant")
    archived = filters.BooleanFilter(method="filter_archived")
    out_of_service = filters.BooleanFilter(method="filter_out_of_service")
    status = filters.MultipleChoiceFilter(choices=EquipmentAsset.Status.choices)

    class Meta:
        model = EquipmentAsset
        fields = ["plant_unit", "category", "criticality", "status"]

    def filter_archived(self, qs, name, value):
        return qs.filter(archived_at__isnull=not value)

    def filter_out_of_service(self, qs, name, value):
        cond = Q(status__in=[EquipmentAsset.Status.OUT_OF_SERVICE, EquipmentAsset.Status.UNDER_MAINTENANCE])
        return qs.filter(cond) if value else qs.exclude(cond)


def annotate_maintenance(qs):
    from apps.maintenance.models import WorkOrder

    open_statuses = WorkOrder.OPEN_STATUSES
    next_pm = (
        WorkOrder.objects.filter(asset=OuterRef("pk"), status__in=open_statuses, due_date__isnull=False)
        .order_by("due_date").values("due_date")[:1]
    )
    return qs.annotate(
        last_maintenance_at=Max("work_orders__actual_end", filter=Q(work_orders__status=WorkOrder.Status.COMPLETED)),
        open_work_orders=Count("work_orders", filter=Q(work_orders__status__in=open_statuses), distinct=True),
        next_maintenance_due=Subquery(next_pm),
    )


class EquipmentAssetViewSet(AuditedModelViewSet):
    serializer_class = EquipmentAssetSerializer
    filterset_class = AssetFilter
    search_fields = ["asset_tag", "name", "manufacturer", "model_number", "serial_number", "location"]
    ordering_fields = ["asset_tag", "name", "status", "criticality", "last_maintenance_at", "next_maintenance_due"]
    action_permissions = {
        "list": "assets.view", "retrieve": "assets.view", "summary": "assets.view",
        "create": "assets.manage", "update": "assets.manage", "partial_update": "assets.manage",
        "archive": "assets.manage",
    }
    http_method_names = ["get", "post", "put", "patch", "head", "options"]  # assets are archived, not deleted

    def get_queryset(self):
        qs = EquipmentAsset.objects.select_related("category", "plant_unit", "plant_unit__plant")
        if "archived" not in self.request.query_params and self.action == "list":
            qs = qs.filter(archived_at__isnull=True)
        return annotate_maintenance(qs).order_by(*EquipmentAsset._meta.ordering)

    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        asset = self.get_object()
        reason = (request.data.get("reason") or "").strip()
        if not reason:
            raise serializers.ValidationError({"reason": "A reason is required to archive an asset."})
        if asset.is_archived:
            raise serializers.ValidationError("Asset is already archived.")
        from apps.maintenance.models import DowntimeEvent, WorkOrder

        if asset.work_orders.filter(status__in=WorkOrder.OPEN_STATUSES).exists():
            raise serializers.ValidationError("Close or cancel the asset's open work orders before archiving it.")
        if DowntimeEvent.objects.filter(asset=asset, ended_at__isnull=True).exists():
            raise serializers.ValidationError("Close the asset's ongoing downtime event before archiving it.")
        with transaction.atomic():
            before = asset.status
            asset.status = EquipmentAsset.Status.RETIRED
            asset.archived_at = timezone.now()
            asset.save(update_fields=["status", "archived_at", "updated_at"])
            asset.maintenance_schedules.update(is_active=False)
            audit.record(request.user, AuditLog.Action.STATUS, asset,
                         changes={"status": {"from": before, "to": asset.status}}, message=f"Archived: {reason}")
        return Response(self.get_serializer(self.get_queryset().get(pk=asset.pk)).data)

    @action(detail=True, methods=["get"])
    def summary(self, request, pk=None):
        """Consolidated asset view: lifetime downtime, costs and work-order counts."""
        from apps.analytics.services import asset_summary

        asset = self.get_object()
        return Response(asset_summary(asset))
