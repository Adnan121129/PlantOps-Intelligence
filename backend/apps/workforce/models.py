"""Lightweight operational workforce model: employees, shifts, assignments, handovers, overtime.

Deliberately not an HR or payroll system. Contact details and rates are visible only
to roles holding `employees.view_contact` / `overtime.view`.
"""
from __future__ import annotations

import datetime as dt

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import Department, Plant, PlantUnit, TimeStampedModel


class Employee(TimeStampedModel):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        INACTIVE = "INACTIVE", "Inactive"

    employee_code = models.CharField(max_length=20, unique=True)
    first_name = models.CharField(max_length=80)
    last_name = models.CharField(max_length=80)
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="employees")
    job_title = models.CharField(max_length=120)
    employment_status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)
    hourly_rate = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True,
                                      help_text="Used only to cost overtime records.")
    user = models.OneToOneField(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                related_name="employee")

    class Meta:
        ordering = ["employee_code"]
        constraints = [models.CheckConstraint(condition=models.Q(hourly_rate__isnull=True) | models.Q(hourly_rate__gte=0),
                                              name="employee_rate_non_negative")]

    def __str__(self) -> str:
        return f"{self.employee_code} {self.full_name}"

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"


class ShiftDefinition(TimeStampedModel):
    plant = models.ForeignKey(Plant, on_delete=models.PROTECT, related_name="shifts")
    code = models.CharField(max_length=10)
    name = models.CharField(max_length=60)
    start_time = models.TimeField()
    end_time = models.TimeField()
    min_staff = models.PositiveSmallIntegerField(default=1, help_text="Minimum staff for full coverage.")
    sequence = models.PositiveSmallIntegerField(default=1)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["plant__code", "sequence"]
        constraints = [models.UniqueConstraint(fields=["plant", "code"], name="uniq_shift_code_per_plant")]

    def __str__(self) -> str:
        return f"{self.name} ({self.start_time:%H:%M}-{self.end_time:%H:%M})"

    def clean(self) -> None:
        if self.start_time == self.end_time:
            raise ValidationError({"end_time": "A shift must have a non-zero duration."})

    @property
    def crosses_midnight(self) -> bool:
        return self.end_time <= self.start_time

    @property
    def duration_hours(self) -> float:
        start = dt.datetime.combine(dt.date.min, self.start_time)
        end = dt.datetime.combine(dt.date.min + dt.timedelta(days=1 if self.crosses_midnight else 0), self.end_time)
        return (end - start).total_seconds() / 3600

    def window(self, business_date: dt.date, tz) -> tuple[dt.datetime, dt.datetime]:
        """Local start/end of this shift for a business date (the date the shift starts)."""
        start = dt.datetime.combine(business_date, self.start_time, tzinfo=tz)
        end_date = business_date + dt.timedelta(days=1) if self.crosses_midnight else business_date
        return start, dt.datetime.combine(end_date, self.end_time, tzinfo=tz)


class ShiftAssignment(TimeStampedModel):
    class Duty(models.TextChoices):
        OPERATIONS = "OPERATIONS", "Operations"
        MAINTENANCE = "MAINTENANCE", "Maintenance"
        SUPERVISION = "SUPERVISION", "Supervision"

    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="shift_assignments")
    shift = models.ForeignKey(ShiftDefinition, on_delete=models.PROTECT, related_name="assignments")
    date = models.DateField(db_index=True)
    plant_unit = models.ForeignKey(PlantUnit, null=True, blank=True, on_delete=models.PROTECT)
    duty = models.CharField(max_length=20, choices=Duty.choices, default=Duty.OPERATIONS)
    notes = models.CharField(max_length=255, blank=True)
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-date", "shift__sequence", "employee__employee_code"]
        constraints = [
            # One shift per employee per day avoids double-booking (a 24h double shift is recorded as overtime).
            models.UniqueConstraint(fields=["employee", "date"], name="uniq_employee_shift_per_day"),
        ]


class ShiftHandover(TimeStampedModel):
    plant_unit = models.ForeignKey(PlantUnit, on_delete=models.PROTECT, related_name="handovers")
    shift = models.ForeignKey(ShiftDefinition, on_delete=models.PROTECT, related_name="handovers")
    date = models.DateField()
    summary = models.TextField()
    outstanding_issues = models.TextField(blank=True)
    safety_notes = models.TextField(blank=True)
    handed_over_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    received_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-date", "-shift__sequence"]
        constraints = [models.UniqueConstraint(fields=["plant_unit", "shift", "date"], name="uniq_handover")]


class OvertimeRecord(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending approval"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="overtime")
    date = models.DateField()
    hours = models.DecimalField(max_digits=5, decimal_places=2)
    rate_multiplier = models.DecimalField(max_digits=4, decimal_places=2, default=1.5)
    cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True,
                               help_text="hours x hourly rate x multiplier, fixed when approved; null if rate unknown.")
    reason = models.CharField(max_length=255)
    work_order = models.ForeignKey("maintenance.WorkOrder", null=True, blank=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-date"]
        constraints = [
            models.CheckConstraint(condition=models.Q(hours__gt=0) & models.Q(hours__lte=16), name="overtime_hours_range"),
            models.CheckConstraint(condition=models.Q(rate_multiplier__gte=1), name="overtime_multiplier_min"),
        ]
