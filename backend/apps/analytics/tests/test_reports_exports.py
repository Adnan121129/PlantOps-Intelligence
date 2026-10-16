import csv
import datetime as dt
import io
from decimal import Decimal

import openpyxl
import pytest
from django.utils import timezone

from apps.analytics.models import ReportRun
from apps.costs.models import OperationalExpense
from apps.maintenance import services as mnt


@pytest.fixture
def downtime(users, asset):
    now = timezone.now()
    return mnt.record_downtime(user=users["OPERATIONS"], asset=asset, downtime_type="UNPLANNED_FAILURE",
                               started_at=now - dt.timedelta(hours=30), ended_at=now - dt.timedelta(hours=27), cause="Trip")


def body(response) -> str:
    return b"".join(response.streaming_content).decode("utf-8-sig")


@pytest.mark.django_db
def test_csv_export_contents_and_metadata(users, client_for, downtime):
    r = client_for(users["MAINTENANCE"]).get("/api/analytics/reports/downtime_analysis/?export=csv")
    assert r.status_code == 200 and r["Content-Type"].startswith("text/csv")
    assert r["X-Report-Code"] == "downtime_analysis" and "X-Report-Generated-At" in r
    rows = list(csv.DictReader(io.StringIO(body(r))))
    assert len(rows) == 1
    assert rows[0]["Asset"] == "U1-P-001" and rows[0]["Hours in period"] == "3.0" and rows[0]["Cause"] == "Trip"
    assert ReportRun.objects.filter(report_code="downtime_analysis", output_format="csv").exists()


@pytest.mark.django_db
def test_xlsx_export_has_data_and_info_sheets(users, client_for, stocked_item):
    r = client_for(users["STORE"]).get("/api/analytics/reports/inventory_status/?export=xlsx")
    assert r.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    data = list(wb["Data"].values)
    assert data[0][0] == "Item" and data[1][0] == "BRG-1" and data[1][4] == 10.0
    info = dict(wb["Report info"].values)
    assert info["Report"] == "Inventory status" and info["Rows"] == 1


@pytest.mark.django_db
def test_json_report_pagination(users, client_for, downtime):
    r = client_for(users["MANAGEMENT"]).get("/api/analytics/reports/downtime_analysis/?page_size=1").json()
    assert r["count"] == 1 and r["columns"][0]["key"] == "asset_tag" and len(r["results"]) == 1


@pytest.mark.django_db
def test_report_permissions(users, client_for):
    store = client_for(users["STORE"])
    assert store.get("/api/analytics/reports/maintenance_cost/").status_code == 403
    codes = {r["code"] for r in store.get("/api/analytics/reports/").json()}
    assert "maintenance_cost" not in codes and "stock_movements" in codes
    assert client_for(users["MANAGEMENT"]).get("/api/analytics/reports/nope/").status_code == 404


@pytest.mark.django_db
def test_spreadsheet_formula_injection_is_neutralised(users, client_for):
    OperationalExpense.objects.create(expense_date=timezone.now().date(), category="OTHER", amount=Decimal("5"),
                                      currency="USD", description="=HYPERLINK(\"http://evil\")",
                                      recorded_by=users["ADMIN"])
    r = client_for(users["MANAGEMENT"]).get("/api/analytics/reports/maintenance_cost/?export=csv")
    row = next(csv.DictReader(io.StringIO(body(r))))
    assert row["Description"].startswith("'=")


@pytest.mark.django_db
def test_bi_api_token_scope(users, client_for, downtime):
    mgr = client_for(users["MANAGEMENT"])
    token = mgr.post("/api/bi/token/").json()["token"]
    from rest_framework.test import APIClient

    pbi = APIClient()
    pbi.credentials(HTTP_AUTHORIZATION=f"Token {token}")
    data = pbi.get("/api/bi/datasets/fact_downtime_events/").json()
    assert data["count"] == 1 and "duration_hours" in data["columns"]
    csv_resp = pbi.get("/api/bi/datasets/dim_asset/?output=csv")
    assert csv_resp.status_code == 200 and b"asset_tag" in csv_resp.content
    assert pbi.get("/api/bi/datasets/pg_user/").status_code == 404           # whitelist only
    assert pbi.get("/api/analytics/dashboard/").status_code in (401, 403)     # token is BI-only
    assert pbi.post("/api/assets/categories/", {"code": "X", "name": "X"}).status_code in (401, 403)
    # employees dimension excludes contact details
    assert "email" not in pbi.get("/api/bi/datasets/dim_employee/").json()["columns"]
