from __future__ import annotations

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from django_filters import rest_framework as filters
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.accounts.permissions import ActionPermission

from . import engine
from .models import Alert, AlertActivity, AlertRule, Notification
from .serializers import AlertDetailSerializer, AlertRuleSerializer, AlertSerializer, NotificationSerializer


def visible_alerts(user):
    """Alerts whose rule audience includes the user's role (administrators see all)."""
    qs = Alert.objects.select_related("rule", "acknowledged_by", "resolved_by")
    if user.role != "ADMIN":
        qs = qs.filter(rule__audience_roles__contains=[user.role])
    return qs


class AlertFilter(filters.FilterSet):
    status = filters.MultipleChoiceFilter(choices=Alert.Status.choices)
    active = filters.BooleanFilter(method="filter_active")
    rule = filters.CharFilter(field_name="rule__code")

    class Meta:
        model = Alert
        fields = ["severity"]

    def filter_active(self, qs, name, value):
        cond = Q(status__in=Alert.ACTIVE_STATUSES)
        return qs.filter(cond) if value else qs.exclude(cond)


class AlertViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [ActionPermission]
    read_permission = "alerts.view"
    action_permissions = {"acknowledge": "alerts.view", "resolve": "alerts.view", "dismiss": "alerts.view",
                          "summary": "alerts.view", "evaluate": "alerts.evaluate"}
    filterset_class = AlertFilter
    search_fields = ["title", "message", "related_label"]
    ordering_fields = ["last_detected_at", "first_detected_at", "severity"]

    def get_queryset(self):
        qs = visible_alerts(self.request.user)
        return qs.prefetch_related("activity__actor") if self.action == "retrieve" else qs

    def get_serializer_class(self):
        return AlertDetailSerializer if self.action == "retrieve" else AlertSerializer

    def list(self, request, *args, **kwargs):
        engine.maybe_auto_evaluate()
        return super().list(request, *args, **kwargs)

    def _act(self, request, *, allowed, target, activity, require_note=False):
        with transaction.atomic():
            alert = Alert.objects.select_for_update().get(pk=self.get_object().pk)
            note = str(request.data.get("note", "")).strip()
            if alert.status not in allowed:
                raise ValidationError(f"An alert that is '{alert.get_status_display()}' cannot be {activity.label.lower()}.")
            if require_note and not note:
                raise ValidationError({"note": "Add a note explaining the decision."})
            now = timezone.now()
            alert.status = target
            if target == Alert.Status.ACKNOWLEDGED:
                alert.acknowledged_by, alert.acknowledged_at = request.user, now
            else:
                alert.resolved_by, alert.resolved_at, alert.resolution_note = request.user, now, note
            alert.save()
            AlertActivity.objects.create(alert=alert, action=activity, actor=request.user, note=note)
        return Response(AlertDetailSerializer(self.get_queryset().prefetch_related("activity__actor").get(pk=alert.pk)).data)

    @action(detail=True, methods=["post"])
    def acknowledge(self, request, pk=None):
        return self._act(request, allowed=[Alert.Status.OPEN], target=Alert.Status.ACKNOWLEDGED,
                         activity=AlertActivity.Action.ACKNOWLEDGED)

    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        return self._act(request, allowed=Alert.ACTIVE_STATUSES, target=Alert.Status.RESOLVED,
                         activity=AlertActivity.Action.RESOLVED, require_note=True)

    @action(detail=True, methods=["post"])
    def dismiss(self, request, pk=None):
        return self._act(request, allowed=Alert.ACTIVE_STATUSES, target=Alert.Status.DISMISSED,
                         activity=AlertActivity.Action.DISMISSED, require_note=True)

    @action(detail=False, methods=["get"])
    def summary(self, request):
        engine.maybe_auto_evaluate()
        active = self.get_queryset().filter(status__in=Alert.ACTIVE_STATUSES)
        by_sev = dict(active.values_list("severity").annotate(n=Count("id")))
        return Response({
            "active": active.count(),
            "by_severity": {s: by_sev.get(s, 0) for s in ("CRITICAL", "WARNING", "INFO")},
            "latest": AlertSerializer(active.order_by("-last_detected_at")[:5], many=True).data,
            "unread_notifications": Notification.objects.filter(recipient=request.user, read_at__isnull=True).count(),
            "last_evaluated_at": AlertRule.objects.order_by("-last_evaluated_at").values_list(
                "last_evaluated_at", flat=True).first(),
        })

    @action(detail=False, methods=["post"])
    def evaluate(self, request):
        return Response({"summary": engine.evaluate_rules(force=True)})


class AlertRuleViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin,
                       viewsets.GenericViewSet):
    serializer_class = AlertRuleSerializer
    permission_classes = [ActionPermission]
    read_permission = "alerts.view"
    action_permissions = {"partial_update": "alerts.rules.manage", "update": "alerts.rules.manage"}
    pagination_class = None
    http_method_names = ["get", "patch", "head", "options"]

    def get_queryset(self):
        engine.ensure_rules()
        return AlertRule.objects.annotate(active_alerts=Count("alerts", filter=Q(alerts__status__in=Alert.ACTIVE_STATUSES)))

    def perform_update(self, serializer):
        from apps.accounts import audit
        from apps.accounts.models import AuditLog

        before = audit.snapshot(serializer.instance)
        rule = serializer.save()
        audit.record(self.request.user, AuditLog.Action.UPDATE, rule, changes=audit.diff(before, audit.snapshot(rule)))


class NotificationViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = NotificationSerializer
    filterset_fields = {"read_at": ["isnull"]}

    def get_queryset(self):
        return Notification.objects.filter(recipient=self.request.user)

    @action(detail=True, methods=["post"])
    def read(self, request, pk=None):
        updated = self.get_queryset().filter(pk=pk, read_at__isnull=True).update(read_at=timezone.now())
        return Response({"updated": updated})

    @action(detail=False, methods=["post"], url_path="read-all")
    def read_all(self, request):
        return Response({"updated": self.get_queryset().filter(read_at__isnull=True).update(read_at=timezone.now())})
