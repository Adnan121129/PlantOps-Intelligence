import pytest
from rest_framework.test import APIClient

from apps.accounts.models import AuditLog
from apps.accounts.roles import PERMISSIONS, Role, has_permission, permissions_for
from conftest import PASSWORD


def test_unknown_permission_fails_loudly():
    with pytest.raises(KeyError):
        has_permission("ADMIN", "does.not.exist")


def test_every_permission_maps_to_known_roles():
    for code, roles in PERMISSIONS.items():
        assert roles <= set(Role.values), code
    assert "users.manage" not in permissions_for("MANAGEMENT")


@pytest.mark.django_db
def test_unauthenticated_requests_are_rejected():
    client = APIClient()
    for path in ["/api/assets/equipment/", "/api/analytics/dashboard/", "/api/auth/users/", "/api/bi/datasets/"]:
        assert client.get(path).status_code in (401, 403), path


@pytest.mark.django_db
def test_login_logout_and_failed_login_audit(users):
    client = APIClient(enforce_csrf_checks=True)
    client.get("/api/auth/csrf/")
    token = client.cookies["csrftoken"].value
    bad = client.post("/api/auth/login/", {"username": "operations", "password": "wrong"}, HTTP_X_CSRFTOKEN=token)
    assert bad.status_code == 400
    assert AuditLog.objects.filter(action="LOGIN_FAILED").exists()
    ok = client.post("/api/auth/login/", {"username": "operations", "password": PASSWORD}, HTTP_X_CSRFTOKEN=token)
    assert ok.status_code == 200 and ok.json()["role"] == "OPERATIONS"
    assert "opsreports.edit" in ok.json()["permissions"]
    token = client.cookies["csrftoken"].value
    assert client.post("/api/auth/logout/", HTTP_X_CSRFTOKEN=token).status_code == 204
    assert client.get("/api/auth/me/").status_code == 403


@pytest.mark.django_db
def test_csrf_enforced_for_session_writes(users):
    client = APIClient(enforce_csrf_checks=True)
    client.login(username="maintenance", password=PASSWORD)
    response = client.post("/api/assets/categories/", {"code": "X", "name": "X"})
    assert response.status_code == 403
    assert "CSRF" in response.json()["detail"]


@pytest.mark.django_db
def test_user_cannot_escalate_own_role(users, client_for):
    client = client_for(users["OPERATIONS"])
    response = client.patch("/api/auth/me/", {"role": "ADMIN", "theme_preference": "dark"}, format="json")
    assert response.status_code == 200
    users["OPERATIONS"].refresh_from_db()
    assert users["OPERATIONS"].role == "OPERATIONS"
    assert users["OPERATIONS"].theme_preference == "dark"
    assert client.patch(f"/api/auth/users/{users['OPERATIONS'].pk}/", {"role": "ADMIN"}, format="json").status_code == 403


@pytest.mark.django_db
def test_admin_cannot_change_own_role_or_deactivate_self(users, client_for):
    admin = users["ADMIN"]
    client = client_for(admin)
    r = client.patch(f"/api/auth/users/{admin.pk}/", {"role": "MANAGEMENT"}, format="json")
    assert r.status_code == 400
    r = client.patch(f"/api/auth/users/{admin.pk}/", {"is_active": False}, format="json")
    assert r.status_code == 400
    r = client.patch(f"/api/auth/users/{users['STORE'].pk}/", {"role": "MAINTENANCE"}, format="json")
    assert r.status_code == 200
    assert AuditLog.objects.filter(action="SECURITY", entity_id=str(users["STORE"].pk)).exists()


@pytest.mark.django_db
def test_admin_creates_user_with_validated_password(users, client_for, unit):
    client = client_for(users["ADMIN"])
    weak = client.post("/api/auth/users/", {"username": "new", "role": "STORE", "password": "123"}, format="json")
    assert weak.status_code == 400
    ok = client.post("/api/auth/users/", {"username": "new", "role": "STORE", "password": "Sufficiently-Long-9",
                                          "assigned_units": [unit.pk]}, format="json")
    assert ok.status_code == 201
    assert "password" not in ok.json()


@pytest.mark.django_db
@pytest.mark.parametrize("role,path,method,expected", [
    ("OPERATIONS", "/api/assets/equipment/", "post", 403),
    ("STORE", "/api/maintenance/work-orders/", "post", 403),
    ("MANAGEMENT", "/api/inventory/transactions/", "post", 403),
    ("OPERATIONS", "/api/costs/expenses/", "get", 403),
    ("STORE", "/api/auth/audit-log/", "get", 403),
    ("MAINTENANCE", "/api/bi/datasets/", "get", 403),
    ("MANAGEMENT", "/api/bi/datasets/", "get", 200),
    ("ADMIN", "/api/auth/audit-log/", "get", 200),
])
def test_role_matrix_enforced_server_side(users, client_for, role, path, method, expected):
    response = getattr(client_for(users[role]), method)(path, {}, format="json")
    assert response.status_code == expected
