"""Base viewsets: role-based action permissions plus automatic audit records."""
from __future__ import annotations

from django.db import transaction
from django.db.models import ProtectedError
from rest_framework import status, viewsets
from rest_framework.exceptions import APIException
from rest_framework.response import Response

from apps.accounts import audit
from apps.accounts.models import AuditLog
from apps.accounts.permissions import ActionPermission


class InUseConflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "This record is referenced by other records and cannot be deleted. Archive or deactivate it instead."


class AuditedModelViewSet(viewsets.ModelViewSet):
    permission_classes = [ActionPermission]
    action_permissions: dict = {}
    read_permission: str | None = None
    audit_create_fields: tuple[str, ...] | None = None

    def get_create_kwargs(self) -> dict:
        return {}

    @transaction.atomic
    def perform_create(self, serializer):
        instance = serializer.save(**self.get_create_kwargs())
        audit.record(self.request.user, AuditLog.Action.CREATE, instance, changes=audit.snapshot(instance))

    @transaction.atomic
    def perform_update(self, serializer):
        before = audit.snapshot(serializer.instance)
        instance = serializer.save()
        changes = audit.diff(before, audit.snapshot(instance))
        if changes:
            audit.record(self.request.user, AuditLog.Action.UPDATE, instance, changes=changes)

    def perform_destroy(self, instance):
        try:
            with transaction.atomic():
                audit.record(self.request.user, AuditLog.Action.DELETE, instance, changes=audit.snapshot(instance))
                instance.delete()
        except ProtectedError as exc:
            raise InUseConflict() from exc


class ReadOnlyAuditedViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [ActionPermission]
    action_permissions: dict = {}
    read_permission: str | None = None


def created(data) -> Response:
    return Response(data, status=status.HTTP_201_CREATED)
