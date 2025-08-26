from django.urls import path, include
from rest_framework.routers import DefaultRouter
from inventory.views import (
    ProductViewSet, LocationViewSet, InventoryLevelViewSet, StockMoveViewSet,
    StockMoveBatchViewSet, ReorderSuggestionView
)

router = DefaultRouter()
router.register("products", ProductViewSet, basename="product")
router.register("locations", LocationViewSet, basename="location")
router.register("inventory/levels", InventoryLevelViewSet, basename="inventory-level")
router.register("stock-moves", StockMoveViewSet, basename="stock-move")
router.register("stock-batches", StockMoveBatchViewSet, basename="stock-batch")

urlpatterns = [
    path("", include(router.urls)),
    path("inventory/reorder-suggestions/", ReorderSuggestionView.as_view(), name="reorder-suggestions"),
]
