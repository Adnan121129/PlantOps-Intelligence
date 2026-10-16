from __future__ import annotations

from django.db import models

from apps.core.models import PlantUnit, TimeStampedModel


class EquipmentCategory(TimeStampedModel):
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "equipment categories"

    def __str__(self) -> str:
        return self.name


class EquipmentAsset(TimeStampedModel):
    class Status(models.TextChoices):
        OPERATIONAL = "OPERATIONAL", "Operational"
        UNDER_MAINTENANCE = "UNDER_MAINTENANCE", "Under maintenance"
        OUT_OF_SERVICE = "OUT_OF_SERVICE", "Out of service"
        RETIRED = "RETIRED", "Retired"

    class Criticality(models.TextChoices):
        HIGH = "HIGH", "High (A) - production critical"
        MEDIUM = "MEDIUM", "Medium (B)"
        LOW = "LOW", "Low (C)"

    asset_tag = models.CharField(max_length=40, unique=True, help_text="Unique asset identifier, e.g. GT1-CMP-001")
    name = models.CharField(max_length=150)
    category = models.ForeignKey(EquipmentCategory, on_delete=models.PROTECT, related_name="assets")
    plant_unit = models.ForeignKey(PlantUnit, on_delete=models.PROTECT, related_name="assets")
    location = models.CharField(max_length=150, blank=True)
    manufacturer = models.CharField(max_length=120, blank=True)
    model_number = models.CharField(max_length=120, blank=True)
    serial_number = models.CharField(max_length=120, blank=True)
    commissioned_on = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPERATIONAL, db_index=True)
    criticality = models.CharField(max_length=10, choices=Criticality.choices, default=Criticality.MEDIUM)
    technical_notes = models.TextField(blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["asset_tag"]
        indexes = [models.Index(fields=["plant_unit", "status"]), models.Index(fields=["category"])]

    def __str__(self) -> str:
        return f"{self.asset_tag} {self.name}"

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None
