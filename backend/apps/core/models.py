"""Plant structure, reference data, system settings and attachments."""
from __future__ import annotations

import uuid
import zoneinfo
from pathlib import Path

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models


def validate_timezone(value: str) -> None:
    try:
        zoneinfo.ZoneInfo(value)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError) as exc:
        raise ValidationError(f"'{value}' is not a valid IANA time zone.") from exc


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Plant(TimeStampedModel):
    class FacilityType(models.TextChoices):
        POWER_GENERATION = "POWER_GENERATION", "Power generation"
        MANUFACTURING = "MANUFACTURING", "Manufacturing"
        PROCESS = "PROCESS", "Process / utilities"
        OTHER = "OTHER", "Other industrial"

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=150)
    facility_type = models.CharField(max_length=30, choices=FacilityType.choices)
    timezone = models.CharField(max_length=64, default="UTC", validators=[validate_timezone])
    currency = models.CharField(max_length=3, default="USD")
    location = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


class PlantUnit(TimeStampedModel):
    """A unit or operational area of a plant (e.g. a generating unit, a line)."""

    class UnitType(models.TextChoices):
        GENERATING_UNIT = "GENERATING_UNIT", "Generating unit"
        PRODUCTION_LINE = "PRODUCTION_LINE", "Production line"
        UTILITY = "UTILITY", "Utility / balance of plant"
        AUXILIARY = "AUXILIARY", "Auxiliary area"

    plant = models.ForeignKey(Plant, on_delete=models.PROTECT, related_name="units")
    code = models.CharField(max_length=20)
    name = models.CharField(max_length=150)
    unit_type = models.CharField(max_length=30, choices=UnitType.choices)
    description = models.TextField(blank=True)
    requires_shift_reports = models.BooleanField(
        default=True, help_text="Expect one operational report per shift per day for this unit."
    )
    capacity = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    capacity_unit = models.CharField(max_length=20, blank=True, help_text="e.g. MW, t/h")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["plant__code", "code"]
        constraints = [models.UniqueConstraint(fields=["plant", "code"], name="uniq_unit_code_per_plant")]

    def __str__(self) -> str:
        return f"{self.plant.code}/{self.code}"


class Department(TimeStampedModel):
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]

    def __str__(self) -> str:
        return self.name


class SystemSetting(models.Model):
    """Typed key/value configuration. Known keys and defaults live in apps.core.settings_registry."""

    key = models.CharField(max_length=80, unique=True)
    value = models.JSONField()
    description = models.CharField(max_length=255, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["key"]

    def __str__(self) -> str:
        return self.key


def attachment_upload_to(instance: "Attachment", filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    return f"attachments/{instance.content_type.model}/{instance.object_id}/{instance.uuid}{suffix}"


class Attachment(models.Model):
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    target = GenericForeignKey("content_type", "object_id")
    file = models.FileField(upload_to=attachment_upload_to)
    original_name = models.CharField(max_length=255)
    size_bytes = models.PositiveIntegerField()
    description = models.CharField(max_length=255, blank=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]
        indexes = [models.Index(fields=["content_type", "object_id"])]


class NumberSequence(models.Model):
    """Gap-tolerant, concurrency-safe counters for human-readable document numbers."""

    key = models.CharField(max_length=40, unique=True)
    last_value = models.PositiveIntegerField(default=0)
