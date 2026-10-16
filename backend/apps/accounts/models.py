from __future__ import annotations

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone

from .roles import Role, has_permission


class User(AbstractUser):
    class Theme(models.TextChoices):
        LIGHT = "light", "Light"
        DARK = "dark", "Dark"
        SYSTEM = "system", "System"

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.MANAGEMENT)
    department = models.ForeignKey("core.Department", null=True, blank=True, on_delete=models.SET_NULL)
    assigned_units = models.ManyToManyField(
        "core.PlantUnit",
        blank=True,
        related_name="responsible_users",
        help_text="Units this user reports on or supervises. Supervisors may only review these units.",
    )
    job_title = models.CharField(max_length=120, blank=True)
    theme_preference = models.CharField(max_length=10, choices=Theme.choices, default=Theme.SYSTEM)

    class Meta:
        ordering = ["username"]

    def has_perm_code(self, permission: str) -> bool:
        return bool(self.is_active and has_permission(self.role, permission))

    @property
    def display_name(self) -> str:
        return self.get_full_name() or self.username


class AuditLog(models.Model):
    class Action(models.TextChoices):
        CREATE = "CREATE", "Create"
        UPDATE = "UPDATE", "Update"
        DELETE = "DELETE", "Delete"
        STATUS = "STATUS", "Status change"
        APPROVE = "APPROVE", "Approve"
        REJECT = "REJECT", "Reject"
        STOCK = "STOCK", "Stock movement"
        LOGIN = "LOGIN", "Login"
        LOGOUT = "LOGOUT", "Logout"
        LOGIN_FAILED = "LOGIN_FAILED", "Failed login"
        SECURITY = "SECURITY", "Security / permissions"

    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=20, choices=Action.choices)
    entity_type = models.CharField(max_length=80, db_index=True)
    entity_id = models.CharField(max_length=64, blank=True)
    entity_repr = models.CharField(max_length=255, blank=True)
    changes = models.JSONField(default=dict, blank=True)
    message = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-timestamp", "-id"]
        indexes = [models.Index(fields=["entity_type", "entity_id"])]

    def __str__(self) -> str:
        return f"{self.timestamp:%Y-%m-%d %H:%M} {self.action} {self.entity_type}#{self.entity_id}"


class ApprovalRecord(models.Model):
    """Immutable history of workflow decisions (submit / approve / reject / reopen / verify)."""

    class Action(models.TextChoices):
        SUBMIT = "SUBMIT", "Submitted"
        APPROVE = "APPROVE", "Approved"
        REJECT = "REJECT", "Rejected"
        REOPEN = "REOPEN", "Reopened for correction"
        VERIFY = "VERIFY", "Verified"
        RETURN = "RETURN", "Returned for rework"

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    target = GenericForeignKey("content_type", "object_id")
    action = models.CharField(max_length=10, choices=Action.choices)
    from_status = models.CharField(max_length=30, blank=True)
    to_status = models.CharField(max_length=30)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="approval_actions")
    comment = models.TextField(blank=True)
    revision = models.PositiveIntegerField(default=1)
    snapshot = models.JSONField(default=dict, blank=True, help_text="Record values at the time of the decision.")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["content_type", "object_id"])]
