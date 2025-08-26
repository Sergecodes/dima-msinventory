from collections import defaultdict
from datetime import timedelta

from _decimal import Decimal
from django.db.models import Sum, ProtectedError
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiParameter
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets, status
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ReadOnlyModelViewSet

from inventory.filters import InventoryLevelFilter, StockMoveFilter, StockMoveBatchFilter
from inventory.models import Product, Location, InventoryLevel, StockMove, StockMoveBatch, StockMoveLine
from inventory.serializers import (
    ProductSerializer, LocationSerializer, InventoryLevelSerializer,
    StockMoveSerializer, StockMoveBatchSerializer, StockMoveBatchCreateSerializer
)
from inventory.services.stock import reverse_stock_move, reverse_stock_batch_move, StockError


class AuthedModelViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]


class AuthedReadOnlyModelViewSet(ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]


@extend_schema(tags=["Products"])
class ProductViewSet(AuthedModelViewSet):
    queryset = Product.objects.all()
    serializer_class = ProductSerializer
    search_fields = ["sku", "name", "barcode", "category"]
    filterset_fields = ["is_active", "category"]
    ordering_fields = ["sku", "name", "sales_price", "cost"]

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError:
            refs = {
                "stock_moves": StockMove.objects.filter(product=instance).count(),
                "stock_batch_lines": StockMoveLine.objects.filter(product=instance).count(),
                "stock_batches": StockMoveBatch.objects.filter(lines__product=instance).distinct().count(),
                "inventory_levels": InventoryLevel.objects.filter(product=instance).count(),
            }
            msg = (
                "Cannot delete product: it is referenced by existing stock data "
                "(moves, batch lines, or inventory levels). Reverse/delete those first."
            )
            return Response({"detail": msg, "references": refs}, status=status.HTTP_409_CONFLICT)


@extend_schema(tags=["Locations"])
class LocationViewSet(AuthedModelViewSet):
    queryset = Location.objects.all()
    serializer_class = LocationSerializer
    search_fields = ["code", "name"]
    ordering_fields = ["code", "name"]

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError:
            refs = {
                "stock_moves_from": StockMove.objects.filter(from_location=instance).count(),
                "stock_moves_to": StockMove.objects.filter(to_location=instance).count(),
                "stock_batches_from": StockMoveBatch.objects.filter(from_location=instance).count(),
                "stock_batches_to": StockMoveBatch.objects.filter(to_location=instance).count(),
                "inventory_levels": InventoryLevel.objects.filter(location=instance).count(),
            }
            msg = "Cannot delete location: it is referenced by existing stock data. Reverse moves or move stock first."
            return Response({"detail": msg, "references": refs}, status=status.HTTP_409_CONFLICT)


@extend_schema(tags=["Inventory Levels"])
class InventoryLevelViewSet(AuthedReadOnlyModelViewSet):
    queryset = InventoryLevel.objects.select_related("product", "location").all()
    serializer_class = InventoryLevelSerializer
    filterset_class = InventoryLevelFilter
    search_fields = ["product__sku", "location__code"]
    ordering_fields = ["on_hand", "product__sku", "location__code"]


@extend_schema(
    tags=["Stock Moves"],
    parameters=[
        OpenApiParameter(name="type", location=OpenApiParameter.QUERY, description="Move type", required=False, type=str),
        OpenApiParameter(name="product_sku", location=OpenApiParameter.QUERY, description="Filter by product SKU (icontains)", required=False, type=str),
        OpenApiParameter(name="from_code", location=OpenApiParameter.QUERY, description="Filter by source location code (icontains)", required=False, type=str),
        OpenApiParameter(name="to_code", location=OpenApiParameter.QUERY, description="Filter by destination location code (icontains)", required=False, type=str),
    ],
)
class StockMoveViewSet(AuthedModelViewSet):
    queryset = StockMove.objects.select_related("product", "from_location", "to_location").all()
    serializer_class = StockMoveSerializer
    filterset_class = StockMoveFilter
    search_fields = ["product__sku", "from_location__code", "to_location__code"]
    ordering_fields = ["timestamp", "qty"]

    def update(self, request, *args, **kwargs):
        return Response({"detail": "Stock moves are immutable; delete and recreate if needed."},
                        status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def partial_update(self, request, *args, **kwargs):
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        move = self.get_object()
        try:
            reverse_stock_move(move)
            return Response(status=status.HTTP_204_NO_CONTENT)
        except StockError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(tags=["Stock Batches"])
class StockMoveBatchViewSet(AuthedModelViewSet):
    queryset = StockMoveBatch.objects.select_related("from_location", "to_location").prefetch_related("lines__product").all()
    serializer_class = StockMoveBatchSerializer
    filterset_class = StockMoveBatchFilter
    ordering_fields = ["timestamp", "created_at"]

    def get_serializer_class(self):
        if self.action == "create":
            return StockMoveBatchCreateSerializer
        return super().get_serializer_class()

    def update(self, request, *args, **kwargs):
        return Response({"detail": "Batches are immutable; delete to reverse."},
                        status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def partial_update(self, request, *args, **kwargs):
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        batch = self.get_object()
        try:
            reverse_stock_batch_move(batch)
            return Response(status=status.HTTP_204_NO_CONTENT)
        except StockError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(tags=["Reorder Suggestions"])
class ReorderSuggestionView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """
        Compute average daily OUTBOUND demand over the last `days` (default 14)
        and suggest qty to reach `coverage_days` of stock (default 7).
        Query params: ?days=14&coverage_days=7&min_qty=0
        """
        days = int(request.query_params.get("days", 14))
        coverage_days = int(request.query_params.get("coverage_days", 7))
        min_qty = Decimal(request.query_params.get("min_qty", "0"))
        now = timezone.now()
        start = now - timedelta(days=days)

        # Single-line OUTBOUND
        single = (StockMove.objects
                  .filter(type=StockMove.OUTBOUND, timestamp__gte=start)
                  .values("product_id")
                  .annotate(qty=Sum("qty")))

        # Batch OUTBOUND
        batched = (StockMoveLine.objects
                   .filter(batch__type=StockMoveBatch.OUTBOUND, batch__timestamp__gte=start)
                   .values("product_id")
                   .annotate(qty=Sum("qty")))

        totals = defaultdict(Decimal)
        for row in single:
            totals[row["product_id"]] += Decimal(row["qty"] or 0)
        for row in batched:
            totals[row["product_id"]] += Decimal(row["qty"] or 0)

        # Current on-hand totals
        onhands = (InventoryLevel.objects
                   .values("product_id")
                   .annotate(on_hand=Sum("on_hand")))
        on_map = {row["product_id"]: Decimal(row["on_hand"] or 0) for row in onhands}

        data = []
        if days <= 0:
            days = 1
        for pid, total_out in totals.items():
            avg_daily = (total_out / Decimal(days)).quantize(Decimal("0.01"))
            on_hand = on_map.get(pid, Decimal("0"))
            target = (avg_daily * Decimal(coverage_days)).quantize(Decimal("0.01"))
            suggested = (target - on_hand)
            if suggested < min_qty:
                continue
            if suggested <= 0:
                continue
            prod = Product.objects.get(id=pid)
            data.append({
                "product": pid,
                "sku": prod.sku,
                "name": prod.name,
                "avg_daily_demand": str(avg_daily),
                "on_hand_total": str(on_hand.quantize(Decimal("0.01"))),
                "suggested_qty": str(suggested.quantize(Decimal("0.01"))),
                "window_days": days,
                "coverage_days": coverage_days,
            })

        # Sort highest need first
        data.sort(key=lambda r: Decimal(r["suggested_qty"]), reverse=True)
        return Response(data)
