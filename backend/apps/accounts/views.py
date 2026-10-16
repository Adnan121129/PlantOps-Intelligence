from __future__ import annotations

from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.db import transaction
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from django_filters import rest_framework as filters
from rest_framework import permissions, serializers, status, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.viewsets import AuditedModelViewSet

from . import audit
from .models import AuditLog, User
from .permissions import ActionPermission
from .serializers import AuditLogSerializer, MeSerializer, PasswordChangeSerializer, UserAdminSerializer


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(max_length=256, style={"input_type": "password"})


@method_decorator(ensure_csrf_cookie, name="dispatch")
class CsrfView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return Response({"csrfToken": get_token(request)})


class LoginView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_scope = "login"

    def post(self, request):
        payload = LoginSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        user = authenticate(request, **payload.validated_data)
        if user is None:
            audit.record(None, AuditLog.Action.LOGIN_FAILED, entity_type="accounts.User",
                         entity_repr=payload.validated_data["username"][:150], message="Invalid credentials")
            # Same message for unknown user / wrong password / inactive account.
            return Response({"detail": "Invalid username or password."}, status=status.HTTP_400_BAD_REQUEST)
        login(request, user)
        audit.record(user, AuditLog.Action.LOGIN, user)
        return Response(MeSerializer(user).data)


class LogoutView(APIView):
    def post(self, request):
        audit.record(request.user, AuditLog.Action.LOGOUT, request.user)
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    def get(self, request):
        return Response(MeSerializer(request.user).data)

    def patch(self, request):
        serializer = MeSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class PasswordChangeView(APIView):
    def post(self, request):
        serializer = PasswordChangeSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        request.user.set_password(serializer.validated_data["new_password"])
        request.user.save(update_fields=["password"])
        update_session_auth_hash(request, request.user)
        audit.record(request.user, AuditLog.Action.SECURITY, request.user, message="Password changed")
        return Response(status=status.HTTP_204_NO_CONTENT)


class UserFilter(filters.FilterSet):
    class Meta:
        model = User
        fields = ["role", "is_active", "department"]


class UserViewSet(AuditedModelViewSet):
    queryset = User.objects.select_related("department").prefetch_related("assigned_units")
    serializer_class = UserAdminSerializer
    filterset_class = UserFilter
    search_fields = ["username", "first_name", "last_name", "email"]
    ordering_fields = ["username", "role", "last_login"]
    action_permissions = {"*": "users.manage"}
    http_method_names = ["get", "post", "patch", "head", "options"]  # users are deactivated, never deleted

    @transaction.atomic
    def perform_update(self, serializer):
        before_role = serializer.instance.role
        super().perform_update(serializer)
        if serializer.instance.role != before_role:
            audit.record(self.request.user, AuditLog.Action.SECURITY, serializer.instance,
                         message=f"Role changed from {before_role} to {serializer.instance.role}")


class AuditLogFilter(filters.FilterSet):
    date_from = filters.IsoDateTimeFilter(field_name="timestamp", lookup_expr="gte")
    date_to = filters.IsoDateTimeFilter(field_name="timestamp", lookup_expr="lt")

    class Meta:
        model = AuditLog
        fields = ["action", "entity_type", "entity_id", "actor"]


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AuditLog.objects.select_related("actor")
    serializer_class = AuditLogSerializer
    permission_classes = [ActionPermission]
    read_permission = "audit.view"
    filterset_class = AuditLogFilter
    search_fields = ["entity_repr", "message", "entity_type"]
    ordering_fields = ["timestamp"]


class UserDirectoryView(APIView):
    """Minimal list of active users (id, name, role) for assignment pickers. Any authenticated user."""

    def get(self, request):
        qs = User.objects.filter(is_active=True).order_by("first_name", "last_name")
        role = request.query_params.get("role")
        if role:
            qs = qs.filter(role=role)
        return Response([{"id": u.id, "display_name": u.display_name, "role": u.role} for u in qs])
