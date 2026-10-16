from django.urls import path

from . import views

urlpatterns = [
    path("dashboard/", views.DashboardView.as_view()),
    path("maintenance/", views.MaintenanceAnalyticsView.as_view()),
    path("inventory/", views.InventoryAnalyticsView.as_view()),
    path("costs/", views.CostAnalyticsView.as_view()),
    path("operations/", views.OperationsAnalyticsView.as_view()),
    path("insights/", views.InsightsView.as_view()),
    path("kpi-dictionary/", views.KpiDictionaryView.as_view()),
    path("reports/", views.ReportListView.as_view()),
    path("reports/<str:code>/", views.ReportRunView.as_view()),
    path("search/", views.GlobalSearchView.as_view()),
]
