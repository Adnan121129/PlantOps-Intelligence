from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("plants", views.PlantViewSet)
router.register("units", views.PlantUnitViewSet)
router.register("departments", views.DepartmentViewSet)
router.register("attachments", views.AttachmentViewSet, basename="attachment")

urlpatterns = [
    path("settings/", views.SystemSettingsView.as_view()),
    path("settings/<str:key>/", views.SystemSettingDetailView.as_view()),
    path("", include(router.urls)),
]
