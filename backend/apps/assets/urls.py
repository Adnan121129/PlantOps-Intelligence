from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("categories", views.EquipmentCategoryViewSet)
router.register("equipment", views.EquipmentAssetViewSet, basename="equipment")

urlpatterns = [path("", include(router.urls))]
