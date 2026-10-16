"""Daily operations: configurable metrics, shift reports, equipment status snapshots, incidents."""
from __future__ import annotations

from django.conf import settings
from django.db import models

from apps.assets.models import EquipmentAsset
from apps.core.models import Plant, PlantUnit, TimeStampedModel
from apps.workforce.models import ShiftDefinition


class MetricDefinition(TimeStampedModel):
    """A configurable operational measurement (e.g. energy generated, fuel consumed).

    Facilities differ, so metrics are data, not code. `valid_min/valid_max` reject
    physically implausible entries; `alert_low/alert_high` raise threshold alerts;
    `target_value` is the per-report target used for performance comparison.
    """

    class Aggregation(models.TextChoices):
        SUM = "SUM", "Sum over reports"
        AVG = "AVG", "Average over reports"

    class Direction(models.TextChoices):
        HIGHER_BETTER = "HIGHER_BETTER", "Higher is better"
        LOWER_BETTER = "LOWER_BETTER", "Lower is better"
        NEUTRAL = "NEUTRAL", "Neutral"

    plant = models.ForeignKey(Plant, on_delete=models.PROTECT, related_name="metrics")
    code = models.CharField(max_length=40)
    name = models.CharField(max_length=120)
    unit = models.CharField(max_length=20, help_text="Unit of measure, e.g. MWh, %, t, m3")
    description = models.TextField(blank=True)
    aggregation = models.CharField(max_length=5, choices=Aggregation.choices, default=Aggregation.SUM)
    direction = models.CharField(max_length=15, choices=Direction.choices, default=Direction.NEUTRAL)
    target_value = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    valid_min = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    valid_max = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    alert_low = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    alert_high = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    is_required = models.BooleanField(default=True, help_text="A value or a missing-data reason is required on submit.")
    is_primary_output = models.BooleanField(
        default=False, help_text="Primary production/energy output; used for cost-per-unit KPIs. One per plant."
    )
    unit_types = models.JSONField(default=list, blank=True,
                                  help_text="Plant unit types this metric applies to; empty means all units.")
    display_order = models.PositiveSmallIntegerField(default=10)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["plant__code", "display_order", "code"]
        constraints = [
            models.UniqueConstraint(fields=["plant", "code"], name="uniq_metric_code_per_plant"),
            models.UniqueConstraint(fields=["plant"], condition=models.Q(is_primary_output=True, is_active=True),
                                    name="one_primary_output_metric_per_plant"),
            models.CheckConstraint(
                condition=(models.Q(valid_min__isnull=True) | models.Q(valid_max__isnull=True)
                           | models.Q(valid_min__lte=models.F("valid_max"))),
                name="metric_valid_range_ordered",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.unit})"

    def applies_to(self, unit: PlantUnit) -> bool:
        return unit.plant_id == self.plant_id and (not self.unit_types or unit.unit_type in self.unit_types)


class OperationalReport(TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SUBMITTED = "SUBMITTED", "Submitted"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    plant_unit = models.ForeignKey(PlantUnit, on_delete=models.PROTECT, related_name="operational_reports")
    shift = models.ForeignKey(ShiftDefinition, on_delete=models.PROTECT, related_name="operational_reports")
    report_date = models.DateField(help_text="Business date on which the shift starts (plant local time).")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT, db_index=True)
    revision = models.PositiveSmallIntegerField(default=1)
    summary = models.TextField(blank=True)
    observations = models.TextField(blank=True, help_text="Unusual observations during the shift.")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_comment = models.TextField(blank=True)

    class Meta:
        ordering = ["-report_date", "-shift__sequence", "plant_unit__code"]
        constraints = [
            models.UniqueConstraint(fields=["plant_unit", "shift", "report_date"], name="uniq_report_per_unit_shift_date"),
        ]
        indexes = [models.Index(fields=["report_date", "status"])]

    def __str__(self) -> str:
        return f"{self.plant_unit} {self.report_date} {self.shift.code}"

    @property
    def is_editable(self) -> bool:
        return self.status in {self.Status.DRAFT, self.Status.REJECTED}


class OperationalMeasurement(models.Model):
    """One metric value on a report. `value=None` means *not recorded*, never zero."""

    report = models.ForeignKey(OperationalReport, on_delete=models.CASCADE, related_name="measurements")
    metric = models.ForeignKey(MetricDefinition, on_delete=models.PROTECT, related_name="measurements")
    value = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    missing_reason = models.CharField(max_length=255, blank=True)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["metric__display_order"]
        constraints = [
            models.UniqueConstraint(fields=["report", "metric"], name="uniq_measurement_per_report_metric"),
            models.CheckConstraint(
                condition=models.Q(value__isnull=False) | ~models.Q(missing_reason=""),
                name="measurement_value_or_missing_reason",
            ),
        ]


class ReportEquipmentStatus(models.Model):
    report = models.ForeignKey(OperationalReport, on_delete=models.CASCADE, related_name="equipment_statuses")
    asset = models.ForeignKey(EquipmentAsset, on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=20, choices=[c for c in EquipmentAsset.Status.choices if c[0] != "RETIRED"])
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["report", "asset"], name="uniq_report_asset_status")]


class OperationalIncident(TimeStampedModel):
    class Severity(models.TextChoices):
        LOW = "LOW", "Low"
        MEDIUM = "MEDIUM", "Medium"
        HIGH = "HIGH", "High"
        CRITICAL = "CRITICAL", "Critical"

    class Category(models.TextChoices):
        EQUIPMENT = "EQUIPMENT", "Equipment fault"
        PROCESS = "PROCESS", "Process deviation"
        SAFETY = "SAFETY", "Safety"
        ENVIRONMENT = "ENVIRONMENT", "Environmental"
        EXTERNAL = "EXTERNAL", "External (grid, fuel supply, weather)"
        OTHER = "OTHER", "Other"

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        INVESTIGATING = "INVESTIGATING", "Under investigation"
        RESOLVED = "RESOLVED", "Resolved"

    incident_number = models.CharField(max_length=20, unique=True)
    plant_unit = models.ForeignKey(PlantUnit, on_delete=models.PROTECT, related_name="incidents")
    asset = models.ForeignKey(EquipmentAsset, null=True, blank=True, on_delete=models.PROTECT, related_name="incidents")
    report = models.ForeignKey(OperationalReport, null=True, blank=True, on_delete=models.SET_NULL, related_name="incidents")
    occurred_at = models.DateTimeField()
    severity = models.CharField(max_length=10, choices=Severity.choices, default=Severity.MEDIUM)
    category = models.CharField(max_length=15, choices=Category.choices, default=Category.EQUIPMENT)
    title = models.CharField(max_length=200)
    description = models.TextField()
    immediate_action = models.TextField(blank=True)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.OPEN, db_index=True)
    reported_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution = models.TextField(blank=True)

    class Meta:
        ordering = ["-occurred_at"]

    def __str__(self) -> str:
        return f"{self.incident_number} {self.title}"
