from __future__ import annotations

from django.contrib.contenttypes.models import ContentType
from django.http import FileResponse
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import audit
from apps.accounts.models import AuditLog
from apps.accounts.permissions import ActionPermission, HasPerm

from .models import Attachment, Department, Plant, PlantUnit, SystemSetting
from .serializers import (
    ATTACHABLE_MODELS,
    AttachmentSerializer,
    DepartmentSerializer,
    PlantSerializer,
    PlantUnitSerializer,
    SystemSettingSerializer,
    setting_rows,
)
from .settings_registry import SPECS
from .viewsets import AuditedModelViewSet

REFERENCE_PERMS = {"*": "reference.manage", "list": "assets.view", "retrieve": "assets.view"}


class PlantViewSet(AuditedModelViewSet):
    queryset = Plant.objects.all()
    serializer_class = PlantSerializer
    action_permissions = REFERENCE_PERMS
    search_fields = ["code", "name"]
    filterset_fields = ["is_active", "facility_type"]

    def perform_update(self, serializer):
        from apps.accounts.middleware import reset_timezone_cache

        super().perform_update(serializer)
        reset_timezone_cache()


class PlantUnitViewSet(AuditedModelViewSet):
    queryset = PlantUnit.objects.select_related("plant")
    serializer_class = PlantUnitSerializer
    action_permissions = REFERENCE_PERMS
    search_fields = ["code", "name"]
    filterset_fields = ["plant", "is_active", "unit_type", "requires_shift_reports"]
    pagination_class = None


class DepartmentViewSet(AuditedModelViewSet):
    queryset = Department.objects.all()
    serializer_class = DepartmentSerializer
    action_permissions = REFERENCE_PERMS
    search_fields = ["code", "name"]
    filterset_fields = ["is_active"]
    pagination_class = None


class SystemSettingsView(APIView):
    permission_classes = [HasPerm.of("assets.view")]

    def get(self, request):
        return Response(setting_rows())


class SystemSettingDetailView(APIView):
    permission_classes = [HasPerm.of("reference.manage")]

    def put(self, request, key: str):
        if key not in SPECS:
            raise NotFound("Unknown setting.")
        serializer = SystemSettingSerializer(data=request.data, context={"key": key})
        serializer.is_valid(raise_exception=True)
        row, _ = SystemSetting.objects.get_or_create(
            key=key, defaults={"value": SPECS[key].default, "description": SPECS[key].description}
        )
        before = row.value
        row.value = serializer.validated_data["value"]
        row.updated_by = request.user
        row.save()
        audit.record(request.user, AuditLog.Action.UPDATE, row, changes={"value": {"from": before, "to": row.value}})
        from apps.accounts.middleware import reset_timezone_cache

        reset_timezone_cache()
        return Response(next(r for r in setting_rows() if r["key"] == key))


# Viewing / attaching files follows the permission to view / edit the parent record.
ATTACHMENT_PERMS = {
    "operations.operationalreport": ("opsreports.view_all", "opsreports.edit"),
    "operations.operationalincident": ("assets.view", "incidents.record"),
    "assets.equipmentasset": ("assets.view", "assets.manage"),
    "maintenance.workorder": ("workorders.view", "workorders.report"),
    "costs.operationalexpense": ("costs.view", "costs.record"),
}


class AttachmentViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
                        mixins.DestroyModelMixin, viewsets.GenericViewSet):
    serializer_class = AttachmentSerializer
    permission_classes = [ActionPermission]
    action_permissions = {"*": "assets.view"}  # coarse gate; per-target checks below

    def _check(self, ct: ContentType, write: bool) -> None:
        view_perm, edit_perm = ATTACHMENT_PERMS[f"{ct.app_label}.{ct.model}"]
        needed = edit_perm if write else view_perm
        if not self.request.user.has_perm_code(needed):
            raise PermissionDenied("You do not have access to attachments on this record.")

    def get_queryset(self):
        qs = Attachment.objects.select_related("uploaded_by", "content_type")
        if self.action == "list":
            target_type = self.request.query_params.get("target_type")
            object_id = self.request.query_params.get("object_id")
            if target_type not in ATTACHABLE_MODELS or not (object_id or "").isdigit():
                return qs.none()
            app_label, model = ATTACHABLE_MODELS[target_type].split(".")
            ct = ContentType.objects.get(app_label=app_label, model=model)
            self._check(ct, write=False)
            qs = qs.filter(content_type=ct, object_id=int(object_id))
        return qs

    def get_object(self):
        obj = super().get_object()
        self._check(obj.content_type, write=self.action == "destroy")
        return obj

    def perform_create(self, serializer):
        self._check(serializer.validated_data["content_type"], write=True)
        instance = serializer.save(uploaded_by=self.request.user)
        audit.record(self.request.user, AuditLog.Action.CREATE, instance,
                     message=f"Attached {instance.original_name} to {instance.content_type.model} #{instance.object_id}")

    def perform_destroy(self, instance):
        audit.record(self.request.user, AuditLog.Action.DELETE, instance, message=f"Removed {instance.original_name}")
        instance.file.delete(save=False)
        instance.delete()

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        obj = self.get_object()
        return FileResponse(obj.file.open("rb"), as_attachment=True, filename=obj.original_name)
