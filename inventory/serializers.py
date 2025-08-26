from django.utils import timezone
from rest_framework import serializers

from inventory.models import Product, Location, InventoryLevel, StockMove, StockMoveBatch, StockMoveLine
from inventory.services.stock import apply_stock_move, apply_stock_batch_move, StockError


class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = ["id", "sku", "name", "barcode", "category", "cost", "sales_price", "is_active"]


class LocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Location
        fields = ["id", "code", "name"]


class InventoryLevelSerializer(serializers.ModelSerializer):
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    location_code = serializers.CharField(source="location.code", read_only=True)

    class Meta:
        model = InventoryLevel
        fields = ["id", "product", "product_sku", "location", "location_code", "on_hand"]
        read_only_fields = ["on_hand"]


class StockMoveSerializer(serializers.ModelSerializer):
    # Read-only fields for display
    product_sku = serializers.CharField(source="product.sku", read_only=True)
    from_code = serializers.CharField(source="from_location.code", read_only=True)
    to_code = serializers.CharField(source="to_location.code", read_only=True)

    class Meta:
        model = StockMove
        fields = [
            "id", "type", "product", "product_sku", "qty",
            "from_location", "from_code", "to_location", "to_code",
            "timestamp", "created_at"
        ]
        read_only_fields = ["created_at"]

    def validate(self, attrs):
        t = attrs.get("type")
        from_loc = attrs.get("from_location")
        to_loc = attrs.get("to_location")
        qty = attrs.get("qty")

        if qty is None or qty <= 0:
            raise serializers.ValidationError({"qty": "Quantity must be positive."})

        if t == StockMove.INBOUND and not to_loc:
            raise serializers.ValidationError({"to_location": "INBOUND requires a destination."})
        if t == StockMove.OUTBOUND and not from_loc:
            raise serializers.ValidationError({"from_location": "OUTBOUND requires a source."})
        if t == StockMove.TRANSFER:
            if not (from_loc and to_loc):
                raise serializers.ValidationError("TRANSFER requires both source and destination.")
            if from_loc == to_loc:
                raise serializers.ValidationError("Source and destination must differ.")

        return attrs

    def create(self, validated_data):
        try:
            return apply_stock_move(
                type=validated_data["type"],
                product=validated_data["product"],
                qty=validated_data["qty"],
                from_location=validated_data.get("from_location"),
                to_location=validated_data.get("to_location"),
                timestamp=validated_data.get("timestamp") or timezone.now(),
            )
        except StockError as e:
            raise serializers.ValidationError({"detail": str(e)})


class StockMoveLineSerializer(serializers.ModelSerializer):
    product_sku = serializers.CharField(source="product.sku", read_only=True)

    class Meta:
        model = StockMoveLine
        fields = ["id", "product", "product_sku", "qty"]


class StockMoveBatchSerializer(serializers.ModelSerializer):
    lines = StockMoveLineSerializer(many=True, read_only=True)
    from_code = serializers.CharField(source="from_location.code", read_only=True)
    to_code = serializers.CharField(source="to_location.code", read_only=True)

    class Meta:
        model = StockMoveBatch
        fields = ["id", "type", "from_location", "from_code", "to_location", "to_code",
                  "timestamp", "created_at", "lines"]
        read_only_fields = ["created_at"]


class StockMoveBatchCreateSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=StockMove.TYPES)
    from_location = serializers.PrimaryKeyRelatedField(queryset=Location.objects.all(), required=False, allow_null=True)
    to_location = serializers.PrimaryKeyRelatedField(queryset=Location.objects.all(), required=False, allow_null=True)
    timestamp = serializers.DateTimeField(required=False)
    lines = serializers.ListField(
        child=serializers.DictField(child=serializers.CharField()), allow_empty=False
    )

    def validate(self, attrs):
        t = attrs.get("type")
        from_loc = attrs.get("from_location")
        to_loc = attrs.get("to_location")
        if t == StockMove.INBOUND and not to_loc:
            raise serializers.ValidationError({"to_location": "INBOUND requires a destination."})
        if t == StockMove.OUTBOUND and not from_loc:
            raise serializers.ValidationError({"from_location": "OUTBOUND requires a source."})
        if t == StockMove.TRANSFER:
            if not (from_loc and to_loc):
                raise serializers.ValidationError("TRANSFER requires both source and destination.")
            if from_loc == to_loc:
                raise serializers.ValidationError("Source and destination must differ.")

        # Coerce lines: expect {product: <id>, qty: <number>}
        coerced = []
        for ln in attrs["lines"]:
            try:
                pid = int(ln.get("product"))
                qty = str(ln.get("qty", "")).strip()
                if not qty:
                    raise ValueError
            except Exception:
                raise serializers.ValidationError({"lines": "Each line must include product (id) and qty."})
            coerced.append({"product": Product.objects.get(id=pid), "qty": qty})
        attrs["lines"] = coerced
        return attrs

    def create(self, validated_data):
        try:
            return apply_stock_batch_move(
                type=validated_data["type"],
                from_location=validated_data.get("from_location"),
                to_location=validated_data.get("to_location"),
                timestamp=validated_data.get("timestamp") or timezone.now(),
                lines=validated_data["lines"],
            )
        except StockError as e:
            raise serializers.ValidationError({"detail": str(e)})
