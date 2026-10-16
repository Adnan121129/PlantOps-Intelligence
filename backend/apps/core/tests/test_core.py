import pytest
from django.core.files.uploadedfile import SimpleUploadedFile


@pytest.mark.django_db
def test_settings_are_validated_and_admin_only(users, client_for, plant):
    admin = client_for(users["ADMIN"])
    assert admin.put("/api/core/settings/pm_compliance_grace_days/", {"value": 2}, format="json").status_code == 200
    assert admin.put("/api/core/settings/pm_compliance_grace_days/", {"value": 99}, format="json").status_code == 400
    assert admin.put("/api/core/settings/unknown/", {"value": 1}, format="json").status_code == 404
    assert client_for(users["MANAGEMENT"]).put("/api/core/settings/pm_compliance_grace_days/", {"value": 1},
                                              format="json").status_code == 403
    rows = {r["key"]: r for r in admin.get("/api/core/settings/").json()}
    assert rows["pm_compliance_grace_days"]["value"] == 2 and rows["slow_moving_days"]["value"] == 90


@pytest.mark.django_db
def test_invalid_timezone_rejected(users, client_for):
    r = client_for(users["ADMIN"]).post("/api/core/plants/", {"code": "X", "name": "X", "facility_type": "OTHER",
                                                              "timezone": "Mars/Base"}, format="json")
    assert r.status_code == 400


@pytest.mark.django_db
def test_attachment_upload_validation(users, client_for, asset, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    client = client_for(users["MAINTENANCE"])
    exe = SimpleUploadedFile("tool.exe", b"MZ...", content_type="application/octet-stream")
    r = client.post("/api/core/attachments/", {"target_type": "equipmentasset", "object_id": asset.pk, "file": exe})
    assert r.status_code == 400
    fake_pdf = SimpleUploadedFile("manual.pdf", b"not a pdf", content_type="application/pdf")
    r = client.post("/api/core/attachments/", {"target_type": "equipmentasset", "object_id": asset.pk, "file": fake_pdf})
    assert r.status_code == 400 and "does not match" in str(r.json())
    pdf = SimpleUploadedFile("manual.pdf", b"%PDF-1.4 test", content_type="application/pdf")
    r = client.post("/api/core/attachments/", {"target_type": "equipmentasset", "object_id": asset.pk, "file": pdf})
    assert r.status_code == 201
    listing = client_for(users["OPERATIONS"]).get(f"/api/core/attachments/?target_type=equipmentasset&object_id={asset.pk}")
    assert listing.json()["count"] == 1
    # viewing is allowed, deleting requires edit rights on the parent record
    assert client_for(users["OPERATIONS"]).delete(f"/api/core/attachments/{r.json()['id']}/").status_code == 403
