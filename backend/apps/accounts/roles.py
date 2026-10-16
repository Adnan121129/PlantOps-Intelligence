"""Role-based permission model.

Every API action is guarded by a named permission. Roles map to permission sets
here, in one place, so the matrix is auditable and testable. The frontend receives
the current user's permission list only to decide which controls to *show*; the
backend re-checks every request.
"""
from __future__ import annotations

from django.db import models


class Role(models.TextChoices):
    ADMIN = "ADMIN", "Administrator"
    OPERATIONS = "OPERATIONS", "Operations Officer"
    MAINTENANCE = "MAINTENANCE", "Maintenance Engineer"
    STORE = "STORE", "Store & Procurement Officer"
    SUPERVISOR = "SUPERVISOR", "Shift Supervisor"
    MANAGEMENT = "MANAGEMENT", "Management / Executive"


ALL = frozenset(Role.values)
A, O, M, S, SUP, MG = (Role.ADMIN, Role.OPERATIONS, Role.MAINTENANCE, Role.STORE, Role.SUPERVISOR, Role.MANAGEMENT)

PERMISSIONS: dict[str, frozenset[str]] = {
    # Administration
    "users.manage": frozenset({A}),
    "reference.manage": frozenset({A}),
    "audit.view": frozenset({A}),
    # Dashboard / analytics
    "dashboard.view": ALL,
    "insights.view": frozenset({A, MG, SUP, M}),
    "bi.access": frozenset({A, MG}),
    # Assets
    "assets.view": ALL,
    "assets.manage": frozenset({A, M}),
    # Daily operations
    "opsreports.view_all": frozenset({A, O, SUP}),  # others see approved reports only
    "opsreports.edit": frozenset({O}),
    "opsreports.review": frozenset({SUP}),
    "opsreports.reopen": frozenset({SUP, A}),
    "incidents.record": frozenset({O, SUP, M}),
    # Maintenance
    "workorders.view": ALL,
    "workorders.report": frozenset({O, SUP, M}),
    "workorders.manage": frozenset({M}),
    "workorders.verify": frozenset({SUP, M}),
    "workorders.cancel": frozenset({SUP, M}),
    "downtime.record": frozenset({O, SUP, M}),
    "pm.manage": frozenset({A, M}),
    # Inventory & procurement
    "inventory.view": ALL,
    "inventory.manage": frozenset({A, S}),
    "stock.receive": frozenset({S}),
    "stock.issue": frozenset({S, M}),
    "stock.return": frozenset({S, M}),
    "stock.adjust": frozenset({S}),
    "procurement.view": frozenset({A, S, MG, M}),
    "procurement.request": frozenset({S, M}),
    "procurement.approve": frozenset({MG}),
    "procurement.order": frozenset({S}),
    # Workforce
    "employees.view": ALL,
    "employees.view_contact": frozenset({A, SUP}),
    "employees.manage": frozenset({A, SUP}),
    "shifts.assign": frozenset({A, SUP}),
    "handovers.write": frozenset({SUP, O}),
    "overtime.manage": frozenset({SUP}),
    "overtime.view": frozenset({A, SUP, MG}),
    # Costs
    "costs.view": frozenset({A, MG, M, SUP}),
    "costs.record": frozenset({A, M}),
    "budgets.manage": frozenset({A}),
    # Alerts
    "alerts.view": ALL,
    "alerts.rules.manage": frozenset({A}),
    "alerts.evaluate": frozenset({A, SUP}),
    # Reports
    "reports.view": ALL,
}


def has_permission(role: str | None, permission: str) -> bool:
    if role is None:
        return False
    try:
        return role in PERMISSIONS[permission]
    except KeyError as exc:  # a typo must fail loudly in tests, never grant access
        raise KeyError(f"Unknown permission '{permission}'") from exc


def permissions_for(role: str | None) -> list[str]:
    return sorted(code for code, roles in PERMISSIONS.items() if role in roles)
