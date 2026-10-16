from __future__ import annotations

import datetime as dt

from django.core.exceptions import ValidationError
from django.db.models import Prefetch
from django_filters import rest_framework as filters
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.permissions import ActionPermission
from apps.assets.models import EquipmentAsset
from apps.core.models import PlantUnit
from apps.core.period import plant_tz, resolve_plant
from apps.core.timeutils import local_today
from apps.core.viewsets import AuditedModelViewSet, created
from apps.workforce.models import ShiftDefinition

from . import services
from .models import MetricDefinition, OperationalIncident, OperationalReport
from .serializers import (
    IncidentSerializer,
    MetricDefinitionSerializer,
    ReportDetailSerializer,
    ReportListSerializer,
    ReportWriteSerializer,
)


class MetricDefinitionViewSet(AuditedModelViewSet):
    queryset = MetricDefinition.objects.select_related("plant")
    serializer_class = MetricDefinitionSerializer
    read_permission = "dashboard.view"
    action_permissions = {"*": "reference.manage"}
    filterset_fields = ["plant", "is_active", "is_primary_output"]
    pagination_class = None


class ReportFilter(filters.FilterSet):
    date_from = filters.DateFilter(field_name="report_date", lookup_expr="gte")
    date_to = filters.DateFilter(field_name="report_date", lookup_expr="lte")
    plant = filters.NumberFilter(field_name="plant_unit__plant")
    unit = filters.NumberFilter(field_name="plant_unit")
    status = filters.MultipleChoiceFilter(choices=OperationalReport.Status.choices)
    mine = filters.BooleanFilter(method="filter_mine")

    class Meta:
        model = OperationalReport
        fields = ["plant_unit", "shift", "status", "report_date"]

    def filter_mine(self, qs, name, value):
        return qs.filter(created_by=self.request.user) if value else qs


class OperationalReportViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [ActionPermission]
    read_permission = "dashboard.view"
    action_permissions = {
        "create": "opsreports.edit", "partial_update": "opsreports.edit", "submit": "opsreports.edit",
        "review": "opsreports.review", "reopen": "opsreports.reopen", "template": "opsreports.edit",
        "missing": "dashboard.view",
    }
    filterset_class = ReportFilter
    search_fields = ["summary", "observations", "plant_unit__code"]
    ordering_fields = ["report_date", "status", "updated_at"]

    def get_queryset(self):
        qs = OperationalReport.objects.select_related("plant_unit", "shift", "created_by", "submitted_by", "reviewed_by")
        if self.action == "retrieve":
            qs = qs.prefetch_related("measurements__metric", "equipment_statuses__asset", "incidents")
        if not self.request.user.has_perm_code("opsreports.view_all"):
            qs = qs.filter(status=OperationalReport.Status.APPROVED)  # management & others: approved data only
        return qs

    def get_serializer_class(self):
        return ReportDetailSerializer if self.action == "retrieve" else ReportListSerializer

    def _detail(self, report):
        report = self.get_queryset().prefetch_related("measurements__metric", "equipment_statuses__asset").get(pk=report.pk)
        return ReportDetailSerializer(report, context=self.get_serializer_context()).data

    def create(self, request):
        payload = ReportWriteSerializer(data=request.data, context={"creating": True})
        payload.is_valid(raise_exception=True)
        report = services.create_report(user=request.user, **payload.validated_data)
        return created(self._detail(report))

    def partial_update(self, request, pk=None):
        report = self.get_object()
        payload = ReportWriteSerializer(data=request.data, partial=True)
        payload.is_valid(raise_exception=True)
        report = services.update_report(report, user=request.user, **payload.validated_data)
        return Response(self._detail(report))

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        return Response(self._detail(services.submit_report(self.get_object(), user=request.user)))

    @action(detail=True, methods=["post"])
    def review(self, request, pk=None):
        decision = request.data.get("decision")
        if decision not in ("approve", "reject"):
            raise ValidationError({"decision": "Use 'approve' or 'reject'."})
        report = services.review_report(self.get_object(), user=request.user, approve=decision == "approve",
                                        comment=str(request.data.get("comment", "")))
        return Response(self._detail(report))

    @action(detail=True, methods=["post"])
    def reopen(self, request, pk=None):
        report = services.reopen_report(self.get_object(), user=request.user, reason=str(request.data.get("reason", "")))
        return Response(self._detail(report))

    @action(detail=False, methods=["get"])
    def template(self, request):
        """Form definition for a unit: shifts, applicable metrics and the unit's equipment."""
        try:
            unit = PlantUnit.objects.select_related("plant").get(pk=int(request.query_params.get("unit", "")))
        except (ValueError, PlantUnit.DoesNotExist) as exc:
            raise ValidationError({"unit": "Choose a valid plant unit."}) from exc
        metrics = services.applicable_metrics(unit)
        return Response({
            "unit": {"id": unit.pk, "code": unit.code, "name": unit.name, "plant_timezone": unit.plant.timezone},
            "today": local_today(plant_tz(unit.plant)).isoformat(),
            "shifts": [{"id": s.pk, "name": s.name, "start_time": s.start_time, "end_time": s.end_time}
                       for s in ShiftDefinition.objects.filter(plant=unit.plant, is_active=True)],
            "metrics": MetricDefinitionSerializer(metrics, many=True).data,
            "assets": [{"id": a.pk, "asset_tag": a.asset_tag, "name": a.name, "status": a.status}
                       for a in EquipmentAsset.objects.filter(plant_unit=unit, archived_at__isnull=True)],
        })

    @action(detail=False, methods=["get"])
    def missing(self, request):
        try:
            today = local_today(plant_tz(resolve_plant(None)))
            date_to = dt.date.fromisoformat(request.query_params.get("date_to") or today.isoformat())
            date_from = dt.date.fromisoformat(request.query_params.get("date_from") or (date_to - dt.timedelta(days=6)).isoformat())
        except ValueError as exc:
            raise ValidationError({"date_from": "Use the YYYY-MM-DD format."}) from exc
        if date_from > date_to or (date_to - date_from).days > 92:
            raise ValidationError({"date_from": "Choose a range of at most 93 days."})
        unit = request.query_params.get("unit")
        gaps = services.missing_reports(date_from, date_to, unit_ids=[int(unit)] if unit and unit.isdigit() else None)
        return Response({"date_from": date_from, "date_to": date_to, "count": len(gaps), "results": gaps})


class IncidentFilter(filters.FilterSet):
    date_from = filters.IsoDateTimeFilter(field_name="occurred_at", lookup_expr="gte")
    date_to = filters.IsoDateTimeFilter(field_name="occurred_at", lookup_expr="lt")
    open = filters.BooleanFilter(method="filter_open")
    unit = filters.NumberFilter(field_name="plant_unit")

    class Meta:
        model = OperationalIncident
        fields = ["plant_unit", "asset", "severity", "category", "status", "report"]

    def filter_open(self, qs, name, value):
        return qs.exclude(status="RESOLVED") if value else qs.filter(status="RESOLVED")


class IncidentViewSet(AuditedModelViewSet):
    serializer_class = IncidentSerializer
    read_permission = "dashboard.view"
    action_permissions = {"create": "incidents.record", "partial_update": "incidents.record",
                          "resolve": "incidents.record"}
    filterset_class = IncidentFilter
    search_fields = ["incident_number", "title", "description"]
    ordering_fields = ["occurred_at", "severity", "status"]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        return OperationalIncident.objects.select_related("plant_unit", "asset", "reported_by").prefetch_related(
            Prefetch("work_orders"))

    def perform_create(self, serializer):
        data = dict(serializer.validated_data)
        data.pop("status", None)
        serializer.instance = services.create_incident(user=self.request.user, **data)

    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        incident = services.resolve_incident(self.get_object(), user=request.user,
                                             resolution=str(request.data.get("resolution", "")))
        return Response(self.get_serializer(incident).data)
