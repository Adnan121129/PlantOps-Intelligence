"""Shared fixtures: a small plant with one unit per type, users for every role, and helpers."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.assets.models import EquipmentAsset, EquipmentCategory
from apps.core.models import Department, Plant, PlantUnit, SystemSetting
from apps.inventory.models import InventoryItem, ItemCategory, Supplier
from apps.inventory.services import post_transaction
from apps.operations.models import MetricDefinition
from apps.workforce.models import Employee, ShiftDefinition

PASSWORD = "Test-Password-123"


@pytest.fixture
def plant(db):
    SystemSetting.objects.create(key="default_plant_code", value="TP")
    return Plant.objects.create(code="TP", name="Test plant", facility_type="POWER_GENERATION", timezone="UTC")


@pytest.fixture
def unit(plant):
    return PlantUnit.objects.create(plant=plant, code="U1", name="Unit 1", unit_type="GENERATING_UNIT", capacity=100)


@pytest.fixture
def unit2(plant):
    return PlantUnit.objects.create(plant=plant, code="U2", name="Unit 2", unit_type="GENERATING_UNIT", capacity=100)


@pytest.fixture
def mnt_dept(db):
    return Department.objects.create(code="MNT", name="Maintenance")


@pytest.fixture
def shifts(plant):
    return [ShiftDefinition.objects.create(plant=plant, code="A", name="Day", start_time=dt.time(6), end_time=dt.time(18),
                                           sequence=1, min_staff=2),
            ShiftDefinition.objects.create(plant=plant, code="B", name="Night", start_time=dt.time(18), end_time=dt.time(6),
                                           sequence=2, min_staff=2)]


@pytest.fixture
def make_user(db, unit, mnt_dept):
    def make(role: str, username: str | None = None, units=(None,)) -> User:
        user = User.objects.create_user(username=username or role.lower(), password=PASSWORD, role=role,
                                        department=mnt_dept if role == "MAINTENANCE" else None)
        chosen = [unit] if units == (None,) else list(units)
        user.assigned_units.set(chosen)
        return user
    return make


@pytest.fixture
def users(make_user):
    return {r: make_user(r) for r in ["ADMIN", "OPERATIONS", "MAINTENANCE", "STORE", "SUPERVISOR", "MANAGEMENT"]}


@pytest.fixture
def client_for():
    def make(user: User) -> APIClient:
        client = APIClient()
        client.force_authenticate(user)
        return client
    return make


@pytest.fixture
def category(db):
    return EquipmentCategory.objects.create(code="PUMP", name="Pump")


@pytest.fixture
def asset(unit, category):
    return EquipmentAsset.objects.create(asset_tag="U1-P-001", name="Feed pump", category=category, plant_unit=unit,
                                         criticality="HIGH")


@pytest.fixture
def asset2(unit, category):
    return EquipmentAsset.objects.create(asset_tag="U1-P-002", name="Spare pump", category=category, plant_unit=unit,
                                         criticality="LOW")


@pytest.fixture
def technician(mnt_dept):
    return Employee.objects.create(employee_code="T1", first_name="Tess", last_name="Tech", department=mnt_dept,
                                   job_title="Technician", hourly_rate=Decimal("40"))


@pytest.fixture
def item(db):
    cat = ItemCategory.objects.create(code="MECH", name="Mechanical")
    sup = Supplier.objects.create(code="S1", name="Supplier 1", quoted_lead_time_days=5)
    return InventoryItem.objects.create(item_code="BRG-1", name="Bearing", category=cat, uom="EA", min_stock_level=2,
                                        reorder_quantity=5, criticality="CRITICAL", preferred_supplier=sup)


@pytest.fixture
def stocked_item(item, users):
    post_transaction(item_id=item.pk, txn_type="RECEIPT", quantity=10, unit_cost=Decimal("100"), user=users["STORE"],
                     reference="OPEN", occurred_at=timezone.now() - dt.timedelta(days=10))
    item.refresh_from_db()
    return item


@pytest.fixture
def metrics(plant):
    energy = MetricDefinition.objects.create(plant=plant, code="ENERGY", name="Energy", unit="MWh", aggregation="SUM",
                                             direction="HIGHER_BETTER", target_value=1000, valid_min=0, valid_max=2000,
                                             is_primary_output=True, unit_types=["GENERATING_UNIT"])
    avail = MetricDefinition.objects.create(plant=plant, code="AVAIL", name="Availability", unit="%", aggregation="AVG",
                                            valid_min=0, valid_max=100, alert_low=80)
    optional = MetricDefinition.objects.create(plant=plant, code="NOTE", name="Optional", unit="x", is_required=False)
    return {"energy": energy, "avail": avail, "optional": optional}
