"""Audit-trail helpers used by services and viewsets."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any, Iterable

from django.contrib.contenttypes.models import ContentType
from django.db import models

from apps.core import clock

from .middleware import current_ip
from .models import ApprovalRecord, AuditLog

SENSITIVE_FIELDS = {"password", "last_login"}


def _jsonable(value: Any) -> Any:
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, models.Model):
        return value.pk
    if hasattr(value, "name") and hasattr(value, "url"):  # FieldFile
        return value.name or None
    return value


def snapshot(instance: models.Model, fields: Iterable[str] | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for field in instance._meta.concrete_fields:
        if field.name in SENSITIVE_FIELDS or (fields is not None and field.name not in fields):
            continue
        data[field.name] = _jsonable(getattr(instance, field.attname))
    return data


def diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        key: {"from": before.get(key), "to": after.get(key)}
        for key in sorted(set(before) | set(after))
        if before.get(key) != after.get(key) and key not in {"updated_at"}
    }


def record(actor, action: str, instance: models.Model | None = None, *, changes: dict | None = None,
           message: str = "", entity_type: str | None = None, entity_id: Any = None, entity_repr: str = "") -> AuditLog:
    if instance is not None:
        entity_type = entity_type or instance._meta.label
        entity_id = instance.pk if entity_id is None else entity_id
        entity_repr = entity_repr or str(instance)[:255]
    return AuditLog.objects.create(
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        action=action,
        entity_type=entity_type or "",
        entity_id="" if entity_id is None else str(entity_id),
        entity_repr=entity_repr[:255],
        changes=changes or {},
        message=message,
        ip_address=current_ip(),
        timestamp=clock.now(),
    )


def record_approval(instance: models.Model, *, action: str, actor, from_status: str, to_status: str,
                    comment: str = "", revision: int = 1, snap: dict | None = None) -> ApprovalRecord:
    return ApprovalRecord.objects.create(
        content_type=ContentType.objects.get_for_model(instance),
        object_id=instance.pk,
        action=action,
        from_status=from_status,
        to_status=to_status,
        actor=actor,
        comment=comment,
        revision=revision,
        snapshot=snap or {},
        created_at=clock.now(),
    )


def approvals_for(instance: models.Model):
    return ApprovalRecord.objects.filter(
        content_type=ContentType.objects.get_for_model(instance), object_id=instance.pk
    ).select_related("actor")
