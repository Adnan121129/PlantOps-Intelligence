"""Alert rules engine storage and user notifications.

AlertRule rows hold the *configuration* (enabled, severity, thresholds, audience).
The evaluation logic for each rule code lives in apps.alerts.rules. An Alert is one
detected condition, identified by (rule, dedup_key). While the condition persists the
same alert is updated (occurrence_count, last_detected_at) instead of creating a new
one; a partial unique index enforces this at the database level.
"""
from __future__ import annotations

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Severity(models.TextChoices):
    INFO = "INFO", "Information"
    WARNING = "WARNING", "Warning"
    CRITICAL = "CRITICAL", "Critical"


class AlertRule(models.Model):
    code = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=120)
    description = models.TextField()
    is_enabled = models.BooleanField(default=True)
    severity = models.CharField(max_length=10, choices=Severity.choices, default=Severity.WARNING)
    params = models.JSONField(default=dict, blank=True)
    audience_roles = models.JSONField(default=list, help_text="Roles that see and act on this rule's alerts.")
    last_evaluated_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["code"]

    def __str__(self) -> str:
        return self.code


class Alert(models.Model):
    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        ACKNOWLEDGED = "ACKNOWLEDGED", "Acknowledged"
        RESOLVED = "RESOLVED", "Resolved"
        DISMISSED = "DISMISSED", "Dismissed"

    ACTIVE_STATUSES = (Status.OPEN, Status.ACKNOWLEDGED)

    rule = models.ForeignKey(AlertRule, on_delete=models.CASCADE, related_name="alerts")
    dedup_key = models.CharField(max_length=120)
    severity = models.CharField(max_length=10, choices=Severity.choices)
    title = models.CharField(max_length=200)
    message = models.TextField(help_text="Why the alert was generated, including the values that triggered it.")
    context = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.OPEN, db_index=True)
    related_content_type = models.ForeignKey(ContentType, null=True, blank=True, on_delete=models.SET_NULL)
    related_object_id = models.PositiveBigIntegerField(null=True, blank=True)
    related_label = models.CharField(max_length=150, blank=True)
    link = models.CharField(max_length=200, blank=True, help_text="Frontend route to the related record.")
    first_detected_at = models.DateTimeField()
    last_detected_at = models.DateTimeField()
    occurrence_count = models.PositiveIntegerField(default=1)
    condition_cleared_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                        related_name="+")
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="+")
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.TextField(blank=True)

    class Meta:
        ordering = ["-last_detected_at"]
        constraints = [
            models.UniqueConstraint(fields=["rule", "dedup_key"], condition=Q(condition_cleared_at__isnull=True),
                                    name="uniq_live_alert_per_condition"),
        ]
        indexes = [models.Index(fields=["status", "severity"])]

    def __str__(self) -> str:
        return f"[{self.severity}] {self.title}"


class AlertActivity(models.Model):
    class Action(models.TextChoices):
        CREATED = "CREATED", "Created"
        REDETECTED = "REDETECTED", "Detected again"
        ACKNOWLEDGED = "ACKNOWLEDGED", "Acknowledged"
        RESOLVED = "RESOLVED", "Resolved"
        DISMISSED = "DISMISSED", "Dismissed"
        REOPENED = "REOPENED", "Reopened"
        CLEARED = "CLEARED", "Condition cleared"

    alert = models.ForeignKey(Alert, on_delete=models.CASCADE, related_name="activity")
    action = models.CharField(max_length=15, choices=Action.choices)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    note = models.TextField(blank=True)
    at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["at", "id"]


class Notification(models.Model):
    """A message for one user (e.g. 'work order assigned to you', 'report rejected')."""

    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    title = models.CharField(max_length=200)
    message = models.TextField(blank=True)
    link = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["recipient", "read_at"])]
