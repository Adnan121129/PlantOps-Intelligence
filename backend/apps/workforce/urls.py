from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("employees", views.EmployeeViewSet)
router.register("shifts", views.ShiftDefinitionViewSet)
router.register("assignments", views.ShiftAssignmentViewSet)
router.register("handovers", views.ShiftHandoverViewSet)
router.register("overtime", views.OvertimeViewSet)

urlpatterns = [
    path("directory/", views.EmployeeDirectoryView.as_view()),
    path("", include(router.urls)),
]
