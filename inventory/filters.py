from django_filters import rest_framework as filters

from inventory.models import InventoryLevel, StockMove, StockMoveBatch


class InventoryLevelFilter(filters.FilterSet):
    product_sku = filters.CharFilter(field_name="product__sku", lookup_expr="icontains")
    location_code = filters.CharFilter(field_name="location__code", lookup_expr="icontains")

    class Meta:
        model = InventoryLevel
        fields = ["product", "location", "product_sku", "location_code"]


class StockMoveFilter(filters.FilterSet):
    product_sku = filters.CharFilter(field_name="product__sku", lookup_expr="icontains")
    from_code = filters.CharFilter(field_name="from_location__code", lookup_expr="icontains")
    to_code = filters.CharFilter(field_name="to_location__code", lookup_expr="icontains")

    class Meta:
        model = StockMove
        fields = ["type", "product", "from_location", "to_location", "product_sku", "from_code", "to_code"]


class StockMoveBatchFilter(filters.FilterSet):
    from_code = filters.CharFilter(field_name="from_location__code", lookup_expr="icontains")
    to_code = filters.CharFilter(field_name="to_location__code", lookup_expr="icontains")

    class Meta:
        model = StockMoveBatch
        fields = ["type", "from_location", "to_location", "from_code", "to_code"]
