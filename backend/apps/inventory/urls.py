from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("categories", views.ItemCategoryViewSet)
router.register("suppliers", views.SupplierViewSet)
router.register("items", views.InventoryItemViewSet)
router.register("transactions", views.StockTransactionViewSet, basename="transaction")
router.register("purchase-requests", views.PurchaseRequestViewSet, basename="purchase-request")
router.register("purchase-orders", views.PurchaseOrderViewSet, basename="purchase-order")
router.register("receipts", views.GoodsReceiptViewSet)

urlpatterns = [path("", include(router.urls))]
