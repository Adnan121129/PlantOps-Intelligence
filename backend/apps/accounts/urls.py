from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("users", views.UserViewSet, basename="user")
router.register("audit-log", views.AuditLogViewSet, basename="audit-log")

urlpatterns = [
    path("csrf/", views.CsrfView.as_view()),
    path("login/", views.LoginView.as_view()),
    path("logout/", views.LogoutView.as_view()),
    path("me/", views.MeView.as_view()),
    path("me/password/", views.PasswordChangeView.as_view()),
    path("directory/", views.UserDirectoryView.as_view()),
    path("", include(router.urls)),
]
