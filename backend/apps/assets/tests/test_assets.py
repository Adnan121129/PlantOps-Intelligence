import pytest
from django.core.exceptions import ValidationError

from apps.accounts.models import AuditLog
from apps.maintenance import services as mnt


@pytest.mark.django_db
def test_maintenance_creates_and_updates_asset_with_audit(users, client_for, unit, category):
    client = client_for(users["MAINTENANCE"])
    r = client.post("/api/assets/equipment/", {"asset_tag": "A-1", "name": "Fan", "category": category.pk,
                                               "plant_unit": unit.pk, "criticality": "LOW"}, format="json")
    assert r.status_code == 201, r.json()
    asset_id = r.json()["id"]
    r = client.patch(f"/api/assets/equipment/{asset_id}/", {"location": "Roof"}, format="json")
    assert r.status_code == 200
    log = AuditLog.objects.filter(entity_type="assets.EquipmentAsset", action="UPDATE").get()
    assert log.changes["location"] == {"from": "", "to": "Roof"}
    dup = client.post("/api/assets/equipment/", {"asset_tag": "A-1", "name": "Dup", "category": category.pk,
                                                 "plant_unit": unit.pk}, format="json")
    assert dup.status_code == 400


@pytest.mark.django_db
def test_assets_cannot_be_deleted_or_set_retired_directly(users, client_for, asset):
    client = client_for(users["MAINTENANCE"])
    assert client.delete(f"/api/assets/equipment/{asset.pk}/").status_code in (403, 405)
    r = client.patch(f"/api/assets/equipment/{asset.pk}/", {"status": "RETIRED"}, format="json")
    assert r.status_code == 400


@pytest.mark.django_db
def test_archive_requires_reason_and_no_open_work(users, client_for, asset):
    client = client_for(users["MAINTENANCE"])
    assert client.post(f"/api/assets/equipment/{asset.pk}/archive/", {}, format="json").status_code == 400
    wo = mnt.create_work_order(user=users["MAINTENANCE"], asset=asset, maintenance_type="CORRECTIVE", title="t",
                               description="d")
    r = client.post(f"/api/assets/equipment/{asset.pk}/archive/", {"reason": "Replaced"}, format="json")
    assert r.status_code == 400
    mnt.cancel(wo, user=users["MAINTENANCE"], reason="Raised in error")
    r = client.post(f"/api/assets/equipment/{asset.pk}/archive/", {"reason": "Replaced"}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "RETIRED"
    # archived assets drop out of the default list and reject new work
    assert all(a["id"] != asset.pk for a in client.get("/api/assets/equipment/").json()["results"])
    asset.refresh_from_db()
    with pytest.raises(ValidationError):
        mnt.create_work_order(user=users["MAINTENANCE"], asset=asset, maintenance_type="CORRECTIVE", title="t",
                              description="d")


@pytest.mark.django_db
def test_asset_filters_and_summary(users, client_for, asset, asset2):
    client = client_for(users["MANAGEMENT"])
    data = client.get("/api/assets/equipment/?criticality=HIGH").json()
    assert [a["asset_tag"] for a in data["results"]] == ["U1-P-001"]
    summary = client.get(f"/api/assets/equipment/{asset.pk}/summary/").json()
    assert summary["mttr_status"] == "insufficient_data" and summary["mttr_hours"] is None
