from django.contrib import admin
from inventory.models import Product, Location, InventoryLevel, StockMove, StockMoveBatch, StockMoveLine


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("sku", "name", "category", "sales_price", "cost", "is_active")
    search_fields = ("sku", "name", "barcode", "category")


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ("code", "name")
    search_fields = ("code", "name")


@admin.register(InventoryLevel)
class InventoryLevelAdmin(admin.ModelAdmin):
    list_display = ("product", "location", "on_hand")
    list_filter = ("location",)


@admin.register(StockMove)
class StockMoveAdmin(admin.ModelAdmin):
    list_display = ("type", "product", "qty", "from_location", "to_location", "timestamp")
    list_filter = ("type", "from_location", "to_location")
    search_fields = ("product__sku",)


@admin.register(StockMoveBatch)
class StockMoveBatchAdmin(admin.ModelAdmin):
    list_display = ("id", "type", "from_location", "to_location", "timestamp", "created_at")
    list_filter = ("type", "from_location", "to_location")
    date_hierarchy = "timestamp"


@admin.register(StockMoveLine)
class StockMoveLineAdmin(admin.ModelAdmin):
    list_display = ("id", "batch", "product", "qty")
    search_fields = ("product__sku", "batch__id")
