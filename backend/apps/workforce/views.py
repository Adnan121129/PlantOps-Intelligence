from __future__ import annotations

import datetime as dt

from django.core.exceptions import ValidationError
from django.db.models import Count
from django.utils import timezone
from django_filters import rest_framework as filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import audit
from apps.accounts.models import AuditLog
from apps.accounts.permissions import HasPerm
from apps.core.viewsets import AuditedModelViewSet

from . import services
from .models import Employee, OvertimeRecord, ShiftAssignment, ShiftDefinition, ShiftHandover
from .serializers import (
    EmployeeSerializer,
    OvertimeRecordSerializer,
    ShiftAssignmentSerializer,
    ShiftDefinitionSerializer,
    ShiftHandoverSerializer,
)


class EmployeeViewSet(AuditedModelViewSet):
    queryset = Employee.objects.select_related("department", "user")
    serializer_class = EmployeeSerializer
    read_permission = "employees.view"
    action_permissions = {"*": "employees.manage"}
    search_fields = ["employee_code", "first_name", "last_name", "job_title"]
    filterset_fields = ["department", "employment_status"]
    ordering_fields = ["employee_code", "last_name"]
    http_method_names = ["get", "post", "patch", "head", "options"]  # deactivate instead of delete


class ShiftDefinitionViewSet(AuditedModelViewSet):
    queryset = ShiftDefinition.objects.select_related("plant")
    serializer_class = ShiftDefinitionSerializer
    read_permission = "employees.view"
    action_permissions = {"*": "reference.manage"}
    filterset_fields = ["plant", "is_active"]
    pagination_class = None


class AssignmentFilter(filters.FilterSet):
    date_from = filters.DateFilter(field_name="date", lookup_expr="gte")
    date_to = filters.DateFilter(field_name="date", lookup_expr="lte")

    class Meta:
        model = ShiftAssignment
        fields = ["employee", "shift", "plant_unit", "duty", "date"]


class ShiftAssignmentViewSet(AuditedModelViewSet):
    queryset = ShiftAssignment.objects.select_related("employee", "shift", "plant_unit")
    serializer_class = ShiftAssignmentSerializer
    read_permission = "employees.view"
    action_permissions = {"*": "shifts.assign", "coverage": "employees.view"}
    filterset_class = AssignmentFilter
    search_fields = ["employee__first_name", "employee__last_name", "employee__employee_code"]

    def get_create_kwargs(self):
        return {"assigned_by": self.request.user}

    @action(detail=False, methods=["get"])
    def coverage(self, request):
        """Staffing coverage per date x shift: assigned headcount against the shift's minimum."""
        try:
            date_from = dt.date.fromisoformat(request.query_params.get("date_from") or timezone.localdate().isoformat())
            date_to = dt.date.fromisoformat(request.query_params.get("date_to") or (date_from + dt.timedelta(days=6)).isoformat())
        except ValueError as exc:
            raise ValidationError({"date_from": "Use the YYYY-MM-DD format."}) from exc
        if date_to < date_from or (date_to - date_from).days > 92:
            raise ValidationError({"date_to": "Choose a range of at most 93 days."})
        shifts = list(ShiftDefinition.objects.filter(is_active=True).order_by("plant_id", "sequence"))
        counts = {(r["date"], r["shift"]): r["n"] for r in ShiftAssignment.objects.filter(
            date__gte=date_from, date__lte=date_to).values("date", "shift").annotate(n=Count("id"))}
        rows, day = [], date_from
        while day <= date_to:
            for s in shifts:
                n = counts.get((day, s.pk), 0)
                status = "UNASSIGNED" if n == 0 else "UNDERSTAFFED" if n < s.min_staff else "COVERED"
                rows.append({"date": day.isoformat(), "shift": s.pk, "shift_name": s.name, "assigned": n,
                             "min_staff": s.min_staff, "status": status})
            day += dt.timedelta(days=1)
        summary = {k: sum(1 for r in rows if r["status"] == k) for k in ("COVERED", "UNDERSTAFFED", "UNASSIGNED")}
        return Response({"date_from": date_from, "date_to": date_to, "summary": summary, "rows": rows})


class HandoverFilter(filters.FilterSet):
    date_from = filters.DateFilter(field_name="date", lookup_expr="gte")
    date_to = filters.DateFilter(field_name="date", lookup_expr="lte")

    class Meta:
        model = ShiftHandover
        fields = ["plant_unit", "shift", "date"]


class ShiftHandoverViewSet(AuditedModelViewSet):
    queryset = ShiftHandover.objects.select_related("plant_unit", "shift", "handed_over_by", "received_by")
    serializer_class = ShiftHandoverSerializer
    read_permission = "employees.view"
    action_permissions = {"create": "handovers.write", "update": "handovers.write", "partial_update": "handovers.write",
                          "acknowledge": "handovers.write"}
    filterset_class = HandoverFilter
    search_fields = ["summary", "outstanding_issues"]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_create_kwargs(self):
        return {"handed_over_by": self.request.user}

    def perform_update(self, serializer):
        if serializer.instance.handed_over_by_id != self.request.user.pk:
            raise ValidationError("Only the author can edit a handover note.")
        super().perform_update(serializer)

    @action(detail=True, methods=["post"])
    def acknowledge(self, request, pk=None):
        handover = self.get_object()
        if handover.received_at:
            raise ValidationError("This handover was already acknowledged.")
        if handover.handed_over_by_id == request.user.pk:
            raise ValidationError("The incoming shift must acknowledge the handover, not its author.")
        handover.received_by, handover.received_at = request.user, timezone.now()
        handover.save(update_fields=["received_by", "received_at", "updated_at"])
        audit.record(request.user, AuditLog.Action.STATUS, handover, message="Handover acknowledged")
        return Response(self.get_serializer(handover).data)


class OvertimeFilter(filters.FilterSet):
    date_from = filters.DateFilter(field_name="date", lookup_expr="gte")
    date_to = filters.DateFilter(field_name="date", lookup_expr="lte")

    class Meta:
        model = OvertimeRecord
        fields = ["employee", "status", "work_order"]


class OvertimeViewSet(AuditedModelViewSet):
    queryset = OvertimeRecord.objects.select_related("employee", "work_order", "recorded_by", "decided_by")
    serializer_class = OvertimeRecordSerializer
    read_permission = "overtime.view"
    action_permissions = {"create": "overtime.manage", "partial_update": "overtime.manage",
                          "decide": "overtime.manage"}
    filterset_class = OvertimeFilter
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_create_kwargs(self):
        return {"recorded_by": self.request.user}

    @action(detail=True, methods=["post"])
    def decide(self, request, pk=None):
        record = services.decide_overtime(self.get_object(), user=request.user,
                                          approve=bool(request.data.get("approve")),
                                          comment=str(request.data.get("comment", "")))
        return Response(self.get_serializer(record).data)


class EmployeeDirectoryView(APIView):
    """Active employees (id, code, name, title) for assignment pickers."""
    permission_classes = [HasPerm.of("employees.view")]

    def get(self, request):
        qs = Employee.objects.filter(employment_status="ACTIVE").select_related("department")
        if request.query_params.get("department"):
            qs = qs.filter(department__code=request.query_params["department"])
        return Response([{"id": e.pk, "employee_code": e.employee_code, "full_name": e.full_name,
                          "job_title": e.job_title, "department": e.department.code} for e in qs])
