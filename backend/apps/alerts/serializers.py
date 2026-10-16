from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.accounts.roles import Role

from .models import Alert, AlertActivity, AlertRule, Notification
from .rules import SPECS, validate_params


class AlertRuleSerializer(serializers.ModelSerializer):
    default_params = serializers.SerializerMethodField()
    active_alerts = serializers.IntegerField(read_only=True)

    class Meta:
        model = AlertRule
        fields = ["id", "code", "name", "description", "is_enabled", "severity", "params", "default_params",
                  "audience_roles", "last_evaluated_at", "active_alerts"]
        read_only_fields = ["code", "name", "description", "last_evaluated_at"]

    def get_default_params(self, obj):
        spec = SPECS.get(obj.code)
        return spec.defaults if spec else {}

    def validate_params(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Parameters must be an object.")
        try:
            return validate_params(self.instance.code, value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict.get("params", exc.messages)) from exc

    def validate_audience_roles(self, value):
        if not isinstance(value, list) or not value or any(r not in Role.values for r in value):
            raise serializers.ValidationError(f"Choose one or more of: {', '.join(Role.values)}.")
        return sorted(set(value))


class AlertActivitySerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source="actor.display_name", read_only=True, default=None)

    class Meta:
        model = AlertActivity
        fields = ["id", "action", "actor_name", "note", "at"]


class AlertSerializer(serializers.ModelSerializer):
    rule_code = serializers.CharField(source="rule.code", read_only=True)
    rule_name = serializers.CharField(source="rule.name", read_only=True)
    acknowledged_by_name = serializers.CharField(source="acknowledged_by.display_name", read_only=True, default=None)
    resolved_by_name = serializers.CharField(source="resolved_by.display_name", read_only=True, default=None)
    is_live = serializers.SerializerMethodField()

    class Meta:
        model = Alert
        fields = ["id", "rule_code", "rule_name", "severity", "title", "message", "context", "status", "related_label",
                  "link", "first_detected_at", "last_detected_at", "occurrence_count", "condition_cleared_at",
                  "is_live", "acknowledged_by_name", "acknowledged_at", "resolved_by_name", "resolved_at",
                  "resolution_note"]

    def get_is_live(self, obj) -> bool:
        return obj.condition_cleared_at is None


class AlertDetailSerializer(AlertSerializer):
    activity = AlertActivitySerializer(many=True, read_only=True)

    class Meta(AlertSerializer.Meta):
        fields = AlertSerializer.Meta.fields + ["activity"]


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ["id", "title", "message", "link", "created_at", "read_at"]
