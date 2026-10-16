from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("alerts", views.AlertViewSet, basename="alert")
router.register("rules", views.AlertRuleViewSet, basename="alert-rule")
router.register("notifications", views.NotificationViewSet, basename="notification")

urlpatterns = [path("", include(router.urls))]
