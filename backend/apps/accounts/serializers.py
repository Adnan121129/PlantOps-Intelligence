from __future__ import annotations

from django.contrib.auth import password_validation
from rest_framework import serializers

from apps.core.models import PlantUnit

from .models import ApprovalRecord, AuditLog, User
from .roles import permissions_for


class MeSerializer(serializers.ModelSerializer):
    role_label = serializers.CharField(source="get_role_display", read_only=True)
    permissions = serializers.SerializerMethodField()
    display_name = serializers.CharField(read_only=True)
    assigned_unit_ids = serializers.PrimaryKeyRelatedField(source="assigned_units", many=True, read_only=True)

    class Meta:
        model = User
        fields = [
            "id", "username", "first_name", "last_name", "display_name", "email", "role", "role_label",
            "job_title", "department", "assigned_unit_ids", "theme_preference", "permissions", "last_login",
        ]
        # Only presentation preferences are self-editable; role, units and department are not.
        read_only_fields = [f for f in fields if f not in {"theme_preference", "first_name", "last_name"}]

    def get_permissions(self, obj: User) -> list[str]:
        return permissions_for(obj.role)


class UserAdminSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, allow_blank=False, style={"input_type": "password"})
    role_label = serializers.CharField(source="get_role_display", read_only=True)
    assigned_units = serializers.PrimaryKeyRelatedField(queryset=PlantUnit.objects.all(), many=True, required=False)
    department_name = serializers.CharField(source="department.name", read_only=True, default=None)

    class Meta:
        model = User
        fields = [
            "id", "username", "first_name", "last_name", "email", "role", "role_label", "job_title",
            "department", "department_name", "assigned_units", "is_active", "last_login", "date_joined", "password",
        ]
        read_only_fields = ["last_login", "date_joined"]

    def validate(self, attrs):
        request = self.context["request"]
        if self.instance is not None and self.instance.pk == request.user.pk:
            if "role" in attrs and attrs["role"] != self.instance.role:
                raise serializers.ValidationError({"role": "You cannot change your own role."})
            if attrs.get("is_active") is False:
                raise serializers.ValidationError({"is_active": "You cannot deactivate your own account."})
        if self.instance is None and not attrs.get("password"):
            raise serializers.ValidationError({"password": "A password is required for new users."})
        if attrs.get("password"):
            candidate = self.instance or User(username=attrs.get("username", ""), email=attrs.get("email", ""))
            password_validation.validate_password(attrs["password"], candidate)
        return attrs

    def create(self, validated_data):
        units = validated_data.pop("assigned_units", [])
        password = validated_data.pop("password")
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        user.assigned_units.set(units)
        return user

    def update(self, instance, validated_data):
        units = validated_data.pop("assigned_units", None)
        password = validated_data.pop("password", None)
        for key, value in validated_data.items():
            setattr(instance, key, value)
        if password:
            instance.set_password(password)
        instance.save()
        if units is not None:
            instance.assigned_units.set(units)
        return instance


class UserBriefSerializer(serializers.ModelSerializer):
    display_name = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = ["id", "username", "display_name", "role"]


class AuditLogSerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source="actor.display_name", read_only=True, default=None)

    class Meta:
        model = AuditLog
        fields = ["id", "timestamp", "actor", "actor_name", "action", "entity_type", "entity_id", "entity_repr",
                  "changes", "message", "ip_address"]


class ApprovalRecordSerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source="actor.display_name", read_only=True)

    class Meta:
        model = ApprovalRecord
        fields = ["id", "action", "from_status", "to_status", "actor", "actor_name", "comment", "revision", "created_at"]


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        user = self.context["request"].user
        if not user.check_password(attrs["current_password"]):
            raise serializers.ValidationError({"current_password": "Current password is incorrect."})
        password_validation.validate_password(attrs["new_password"], user)
        return attrs
