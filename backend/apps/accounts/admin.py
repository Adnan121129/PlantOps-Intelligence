from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import AuditLog, User


@admin.register(User)
class PlantOpsUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("PlantOps", {"fields": ("role", "department", "assigned_units", "job_title")}),)
    list_display = ("username", "email", "role", "is_active")
    list_filter = ("role", "is_active")


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "actor", "action", "entity_type", "entity_id")
    list_filter = ("action",)
    readonly_fields = [f.name for f in AuditLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
