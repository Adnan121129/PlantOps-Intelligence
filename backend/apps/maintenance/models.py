"""Maintenance management: preventive schedules, work orders, downtime events, inspections.

Source-of-truth rules
---------------------
* Downtime is *derived* from DowntimeEvent start/end timestamps. It is never typed in
  as a duration. A work order's downtime is the sum of its linked events, so the same
  outage is never counted twice.
* A PostgreSQL exclusion constraint forbids overlapping downtime events on one asset.
* Work-order costs live in the cost ledger (costs.OperationalExpense) linked to the work
  order; parts cost is posted automatically when stock is issued against the work order.
"""
from __future__ import annotations

import datetime as dt

from django.conf import settings
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateTimeRangeField, RangeOperators
from django.db import models
from django.db.models import Func, Q

from apps.assets.models import EquipmentAsset
from apps.core.models import TimeStampedModel
from apps.workforce.models import Employee


class TsTzRange(Func):
    function = "TSTZRANGE"
    output_field = DateTimeRangeField()


class MaintenanceSchedule(TimeStampedModel):
    """A recurring preventive or inspection task on a fixed calendar interval.

    Due dates are `start_date + n * interval_days`. Completing a task late does not shift
    later due dates, so compliance is measured against the original plan.
    """

    class TaskType(models.TextChoices):
        PREVENTIVE = "PREVENTIVE", "Preventive maintenance"
        INSPECTION = "INSPECTION", "Inspection"

    asset = models.ForeignKey(EquipmentAsset, on_delete=models.PROTECT, related_name="maintenance_schedules")
    title = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    task_type = models.CharField(max_length=12, choices=TaskType.choices, default=TaskType.PREVENTIVE)
    interval_days = models.PositiveIntegerField()
    start_date = models.DateField(help_text="First due date.")
    lead_days = models.PositiveIntegerField(default=7, help_text="Work orders are generated this many days before due.")
    reminder_days = models.PositiveIntegerField(default=3, help_text="'Upcoming' alert is raised this many days before due.")
    estimated_hours = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    default_technician = models.ForeignKey(Employee, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    priority = models.CharField(max_length=10, default="MEDIUM")
    last_generated_due_date = models.DateField(null=True, blank=True, editable=False)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["asset__asset_tag", "title"]
        constraints = [
            models.UniqueConstraint(fields=["asset", "title"], name="uniq_schedule_title_per_asset"),
            models.CheckConstraint(condition=Q(interval_days__gte=1), name="schedule_interval_positive"),
        ]

    def __str__(self) -> str:
        return f"{self.asset.asset_tag}: {self.title} every {self.interval_days}d"

    def due_dates_between(self, start: dt.date, end: dt.date) -> list[dt.date]:
        if end < self.start_date:
            return []
        first_n = max(0, -(-(start - self.start_date).days // self.interval_days))
        dates, n = [], first_n
        while True:
            due = self.start_date + dt.timedelta(days=n * self.interval_days)
            if due > end:
                return dates
            if due >= start:
                dates.append(due)
            n += 1

    @property
    def next_generation_due_date(self) -> dt.date:
        if self.last_generated_due_date is None:
            return self.start_date
        return self.last_generated_due_date + dt.timedelta(days=self.interval_days)


class WorkOrder(TimeStampedModel):
    class MaintenanceType(models.TextChoices):
        CORRECTIVE = "CORRECTIVE", "Corrective"
        PREVENTIVE = "PREVENTIVE", "Preventive"
        INSPECTION = "INSPECTION", "Inspection"

    class Priority(models.TextChoices):
        LOW = "LOW", "Low"
        MEDIUM = "MEDIUM", "Medium"
        HIGH = "HIGH", "High"
        CRITICAL = "CRITICAL", "Critical"

    class Status(models.TextChoices):
        REPORTED = "REPORTED", "Reported"
        ASSIGNED = "ASSIGNED", "Assigned"
        IN_PROGRESS = "IN_PROGRESS", "In progress"
        AWAITING_VERIFICATION = "AWAITING_VERIFICATION", "Awaiting verification"
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"

    class FailureCode(models.TextChoices):
        MECHANICAL = "MECHANICAL", "Mechanical"
        ELECTRICAL = "ELECTRICAL", "Electrical"
        INSTRUMENTATION = "INSTRUMENTATION", "Instrumentation & control"
        LUBRICATION = "LUBRICATION", "Lubrication"
        CORROSION = "CORROSION", "Corrosion / wear"
        OPERATIONAL = "OPERATIONAL", "Operating error"
        EXTERNAL = "EXTERNAL", "External cause"
        UNKNOWN = "UNKNOWN", "Not established"

    OPEN_STATUSES = (Status.REPORTED, Status.ASSIGNED, Status.IN_PROGRESS, Status.AWAITING_VERIFICATION)
    CLOSED_STATUSES = (Status.COMPLETED, Status.CANCELLED)

    number = models.CharField(max_length=20, unique=True)
    asset = models.ForeignKey(EquipmentAsset, on_delete=models.PROTECT, related_name="work_orders")
    schedule = models.ForeignKey(MaintenanceSchedule, null=True, blank=True, on_delete=models.PROTECT,
                                 related_name="work_orders")
    incident = models.ForeignKey("operations.OperationalIncident", null=True, blank=True, on_delete=models.SET_NULL,
                                 related_name="work_orders")
    maintenance_type = models.CharField(max_length=12, choices=MaintenanceType.choices, db_index=True)
    title = models.CharField(max_length=200)
    description = models.TextField()
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    status = models.CharField(max_length=25, choices=Status.choices, default=Status.REPORTED, db_index=True)
    reported_at = models.DateTimeField()
    reported_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    assigned_technician = models.ForeignKey(Employee, null=True, blank=True, on_delete=models.PROTECT,
                                            related_name="work_orders")
    assigned_team = models.CharField(max_length=80, blank=True)
    due_date = models.DateField(null=True, blank=True, help_text="Scheduled due date (preventive/inspection tasks).")
    planned_start = models.DateTimeField(null=True, blank=True)
    planned_end = models.DateTimeField(null=True, blank=True)
    actual_start = models.DateTimeField(null=True, blank=True)
    actual_end = models.DateTimeField(null=True, blank=True)
    failure_code = models.CharField(max_length=20, choices=FailureCode.choices, blank=True)
    root_cause = models.TextField(blank=True)
    actions_performed = models.TextField(blank=True)
    completion_notes = models.TextField(blank=True)
    labor_hours = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    requires_verification = models.BooleanField(default=True)
    completed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    verified_at = models.DateTimeField(null=True, blank=True)
    verification_comment = models.TextField(blank=True)
    cancelled_reason = models.TextField(blank=True)
    cancelled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")
    cancelled_at = models.DateTimeField(null=True, blank=True)
    # "Blocked" is an indicator layered on top of the lifecycle (e.g. waiting for parts).
    is_blocked = models.BooleanField(default=False)
    blocked_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-reported_at"]
        constraints = [
            models.UniqueConstraint(fields=["schedule", "due_date"], condition=Q(schedule__isnull=False),
                                    name="uniq_pm_work_order_per_due_date"),
            models.CheckConstraint(condition=Q(planned_end__isnull=True) | Q(planned_start__isnull=True) |
                                   Q(planned_end__gte=models.F("planned_start")), name="wo_planned_window_ordered"),
            models.CheckConstraint(condition=Q(actual_end__isnull=True) | Q(actual_start__isnull=True) |
                                   Q(actual_end__gte=models.F("actual_start")), name="wo_actual_window_ordered"),
            models.CheckConstraint(condition=~Q(status="CANCELLED") | ~Q(cancelled_reason=""),
                                   name="wo_cancel_requires_reason"),
            models.CheckConstraint(condition=Q(labor_hours__isnull=True) | Q(labor_hours__gte=0),
                                   name="wo_labor_hours_non_negative"),
        ]
        indexes = [models.Index(fields=["asset", "status"]), models.Index(fields=["due_date"])]

    def __str__(self) -> str:
        return f"{self.number} {self.title}"

    @property
    def is_open(self) -> bool:
        return self.status in self.OPEN_STATUSES

    def overdue_reference(self) -> dt.datetime | dt.date | None:
        return self.planned_end or self.due_date


class DowntimeEvent(TimeStampedModel):
    class DowntimeType(models.TextChoices):
        UNPLANNED_FAILURE = "UNPLANNED_FAILURE", "Unplanned - equipment failure"
        PLANNED_MAINTENANCE = "PLANNED_MAINTENANCE", "Planned maintenance"
        EXTERNAL = "EXTERNAL", "External (grid, fuel, weather)"
        OPERATIONAL = "OPERATIONAL", "Operational / process"

    asset = models.ForeignKey(EquipmentAsset, on_delete=models.PROTECT, related_name="downtime_events")
    work_order = models.ForeignKey(WorkOrder, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="downtime_events")
    incident = models.ForeignKey("operations.OperationalIncident", null=True, blank=True, on_delete=models.SET_NULL,
                                 related_name="downtime_events")
    downtime_type = models.CharField(max_length=20, choices=DowntimeType.choices)
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True, help_text="Empty while the outage is ongoing.")
    cause = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["-started_at"]
        constraints = [
            models.CheckConstraint(condition=Q(ended_at__isnull=True) | Q(ended_at__gt=models.F("started_at")),
                                   name="downtime_end_after_start"),
            ExclusionConstraint(
                name="downtime_no_overlap_per_asset",
                expressions=[
                    (TsTzRange("started_at", "ended_at"), RangeOperators.OVERLAPS),
                    ("asset", RangeOperators.EQUAL),
                ],
            ),
        ]
        indexes = [models.Index(fields=["asset", "started_at"]), models.Index(fields=["started_at", "ended_at"])]

    def __str__(self) -> str:
        return f"{self.asset.asset_tag} {self.started_at:%Y-%m-%d %H:%M}"

    @property
    def is_ongoing(self) -> bool:
        return self.ended_at is None

    @property
    def duration_hours(self) -> float | None:
        if self.ended_at is None:
            return None
        return round((self.ended_at - self.started_at).total_seconds() / 3600, 2)


class InspectionRecord(TimeStampedModel):
    class Result(models.TextChoices):
        PASS = "PASS", "Pass"
        ATTENTION = "ATTENTION", "Needs attention"
        FAIL = "FAIL", "Fail"

    asset = models.ForeignKey(EquipmentAsset, on_delete=models.PROTECT, related_name="inspections")
    work_order = models.ForeignKey(WorkOrder, null=True, blank=True, on_delete=models.PROTECT, related_name="inspections")
    inspected_at = models.DateTimeField()
    inspector = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    result = models.CharField(max_length=10, choices=Result.choices)
    findings = models.TextField()
    readings = models.TextField(blank=True, help_text="Measured values, e.g. vibration mm/s, temperatures.")
    follow_up_work_order = models.ForeignKey(WorkOrder, null=True, blank=True, on_delete=models.SET_NULL,
                                             related_name="+")

    class Meta:
        ordering = ["-inspected_at"]
