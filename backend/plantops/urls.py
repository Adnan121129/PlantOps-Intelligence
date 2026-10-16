from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("api/auth/", include("apps.accounts.urls")),
    path("api/core/", include("apps.core.urls")),
    path("api/assets/", include("apps.assets.urls")),
    path("api/workforce/", include("apps.workforce.urls")),
    path("api/operations/", include("apps.operations.urls")),
    path("api/maintenance/", include("apps.maintenance.urls")),
    path("api/inventory/", include("apps.inventory.urls")),
    path("api/costs/", include("apps.costs.urls")),
    path("api/alerts/", include("apps.alerts.urls")),
    path("api/analytics/", include("apps.analytics.urls")),
    path("api/bi/", include("apps.bi.urls")),
]
