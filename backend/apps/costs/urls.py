from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("expenses", views.ExpenseViewSet, basename="expense")
router.register("budgets", views.BudgetViewSet)

urlpatterns = [path("", include(router.urls))]
