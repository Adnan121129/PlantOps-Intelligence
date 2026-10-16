from __future__ import annotations

import itertools

from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import HasPerm
from apps.core.period import period_from_params

from . import dashboard as dash
from .exports import csv_response, stamp, xlsx_response
from .insights import insights
from .kpis import KPIS
from .models import ReportRun
from .reports import REPORTS
from .services import Scope


def scope_from(request, default_days: int = 30) -> Scope:
    period, plant, unit = period_from_params(request.query_params, default_days=default_days)
    return Scope(period, plant, unit)


def _granularity(request) -> str:
    g = request.query_params.get("granularity", "day")
    if g not in ("day", "week", "month"):
        raise ValidationError({"granularity": "Use day, week or month."})
    return g


class DashboardView(APIView):
    permission_classes = [HasPerm.of("dashboard.view")]

    def get(self, request):
        return Response(dash.dashboard(scope_from(request), request.user, _granularity(request)))


class MaintenanceAnalyticsView(APIView):
    permission_classes = [HasPerm.of("workorders.view")]

    def get(self, request):
        return Response(dash.maintenance_analytics(scope_from(request, 90), request.query_params.get("granularity", "week")
                                                   if request.query_params.get("granularity") in ("day", "week", "month")
                                                   else "week"))


class InventoryAnalyticsView(APIView):
    permission_classes = [HasPerm.of("inventory.view")]

    def get(self, request):
        return Response(dash.inventory_analytics(scope_from(request, 180)))


class CostAnalyticsView(APIView):
    permission_classes = [HasPerm.of("costs.view")]

    def get(self, request):
        return Response(dash.cost_analytics(scope_from(request, 180)))


class OperationsAnalyticsView(APIView):
    permission_classes = [HasPerm.of("dashboard.view")]

    def get(self, request):
        metric = request.query_params.get("metric")
        return Response(dash.operations_analytics(scope_from(request), int(metric) if metric and metric.isdigit() else None))


class InsightsView(APIView):
    permission_classes = [HasPerm.of("insights.view")]

    def get(self, request):
        scope = scope_from(request)
        return Response({"period": scope.period.as_dict(), "engine": "rule-based", "insights": insights(scope, request.user)})


class KpiDictionaryView(APIView):
    permission_classes = [HasPerm.of("dashboard.view")]

    def get(self, request):
        return Response([{"code": code, **meta} for code, meta in KPIS.items()])


class ReportListView(APIView):
    permission_classes = [HasPerm.of("reports.view")]

    def get(self, request):
        return Response([{"code": r.code, "title": r.title, "description": r.description}
                         for r in REPORTS.values() if request.user.has_perm_code(r.permission)])


class ReportRunView(APIView):
    """GET /api/analytics/reports/<code>/?date_from&date_to&unit&format=json|csv|xlsx&page&page_size"""
    permission_classes = [HasPerm.of("reports.view")]

    def get(self, request, code: str):
        report = REPORTS.get(code)
        if report is None:
            raise NotFound("Unknown report.")
        if not request.user.has_perm_code(report.permission):
            raise PermissionDenied("You do not have access to this report.")
        fmt = request.query_params.get("export") or request.query_params.get("output") or "json"
        if fmt not in ("json", "csv", "xlsx"):
            raise ValidationError({"output": "Use json, csv or xlsx."})
        scope = scope_from(request)
        columns = report.columns(scope)
        rows = report.rows(scope, request.user)
        meta = {"Code": report.code, "Period-From": scope.period.date_from, "Period-To": scope.period.date_to,
                "Timezone": scope.period.tz, "Unit": scope.unit.code if scope.unit else "All",
                "Generated-At": timezone.now().isoformat(),
                "Generated-By": request.user.username}
        params = {k: v for k, v in request.query_params.items() if k in ("date_from", "date_to", "unit", "plant")}
        filename = f"{report.code}_{scope.period.date_from}_{scope.period.date_to}_{stamp()}"
        headers, keys = [c.label for c in columns], [c.key for c in columns]
        if fmt == "csv":
            ReportRun.objects.create(report_code=code, output_format="csv", params=params, generated_by=request.user)
            return csv_response(filename, headers, keys, rows, meta)
        if fmt == "xlsx":
            rows = list(rows)
            ReportRun.objects.create(report_code=code, output_format="xlsx", params=params, generated_by=request.user,
                                     row_count=len(rows))
            return xlsx_response(filename, report.title, headers, keys, rows, meta)
        try:
            page = max(int(request.query_params.get("page", 1)), 1)
            size = min(max(int(request.query_params.get("page_size", 50)), 1), 500)
        except ValueError as exc:
            raise ValidationError({"page": "Must be an integer."}) from exc
        all_rows = list(rows)
        ReportRun.objects.create(report_code=code, output_format="json", params=params, generated_by=request.user,
                                 row_count=len(all_rows))
        start = (page - 1) * size
        return Response({
            "report": {"code": report.code, "title": report.title, "description": report.description},
            "period": scope.period.as_dict(), "generated_at": meta["Generated-At"],
            "columns": [{"key": c.key, "label": c.label, "kind": c.kind} for c in columns],
            "count": len(all_rows), "page": page, "page_size": size,
            "results": list(itertools.islice(all_rows, start, start + size)),
        })


class GlobalSearchView(APIView):
    """Lightweight cross-module search for the header search box (max 5 hits per type, permission-aware)."""
    permission_classes = [HasPerm.of("dashboard.view")]

    def get(self, request):
        from apps.assets.models import EquipmentAsset
        from apps.inventory.models import InventoryItem
        from apps.maintenance.models import WorkOrder
        from apps.operations.models import OperationalIncident

        q = (request.query_params.get("q") or "").strip()
        if len(q) < 2:
            return Response({"results": []})
        user = request.user
        results = []
        if user.has_perm_code("assets.view"):
            results += [{"type": "Asset", "label": f"{a.asset_tag} {a.name}", "link": f"/assets/{a.pk}"}
                        for a in EquipmentAsset.objects.filter(Q(asset_tag__icontains=q) | Q(name__icontains=q))[:5]]
        if user.has_perm_code("workorders.view"):
            results += [{"type": "Work order", "label": f"{w.number} {w.title}", "link": f"/maintenance/work-orders/{w.pk}"}
                        for w in WorkOrder.objects.filter(Q(number__icontains=q) | Q(title__icontains=q))[:5]]
        if user.has_perm_code("inventory.view"):
            results += [{"type": "Item", "label": f"{i.item_code} {i.name}", "link": f"/inventory/items/{i.pk}"}
                        for i in InventoryItem.objects.filter(Q(item_code__icontains=q) | Q(name__icontains=q))[:5]]
        results += [{"type": "Incident", "label": f"{i.incident_number} {i.title}", "link": f"/operations/incidents?id={i.pk}"}
                    for i in OperationalIncident.objects.filter(Q(incident_number__icontains=q) | Q(title__icontains=q))[:5]]
        return Response({"results": results})
