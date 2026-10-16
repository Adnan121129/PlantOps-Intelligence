from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("work-orders", views.WorkOrderViewSet, basename="work-order")
router.register("downtime", views.DowntimeViewSet, basename="downtime")
router.register("schedules", views.ScheduleViewSet, basename="schedule")
router.register("inspections", views.InspectionViewSet)

urlpatterns = [path("", include(router.urls))]
