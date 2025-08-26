from django.db import models
from django.utils import timezone


class Product(models.Model):
    sku = models.CharField(max_length=64, unique=True)    # "Internal Reference"
    name = models.CharField(max_length=255)
    barcode = models.CharField(max_length=64, blank=True, null=True)
    category = models.CharField(max_length=255, blank=True, null=True)
    cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)         # optional
    sales_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)  # optional
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sku"]

    def __str__(self):
        return f"{self.sku} - {self.name}"


class Location(models.Model):
    code = models.CharField(max_length=32, unique=True)  # e.g., MAIN, STAGING, RETURNS
    name = models.CharField(max_length=255)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} ({self.name})"


class InventoryLevel(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="levels")
    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name="levels")
    on_hand = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    class Meta:
        unique_together = [("product", "location")]
        ordering = ["product__sku", "location__code"]

    def __str__(self):
        return f"{self.product.sku} @ {self.location.code}: {self.on_hand}"


class StockMove(models.Model):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"
    TRANSFER = "TRANSFER"
    TYPES = [(INBOUND, "INBOUND"), (OUTBOUND, "OUTBOUND"), (TRANSFER, "TRANSFER")]

    type = models.CharField(max_length=10, choices=TYPES)
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="stock_moves")
    qty = models.DecimalField(max_digits=14, decimal_places=2)
    from_location = models.ForeignKey(
        Location, on_delete=models.PROTECT, related_name="out_moves", blank=True, null=True
    )
    to_location = models.ForeignKey(
        Location, on_delete=models.PROTECT, related_name="in_moves", blank=True, null=True
    )
    timestamp = models.DateTimeField(default=timezone.now)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp", "-id"]

    def __str__(self):
        return f"{self.type} {self.qty} {self.product.sku} ({self.from_location}->{self.to_location})"


class StockMoveBatch(models.Model):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"
    TRANSFER = "TRANSFER"
    TYPES = [(INBOUND, "INBOUND"), (OUTBOUND, "OUTBOUND"), (TRANSFER, "TRANSFER")]

    type = models.CharField(max_length=10, choices=TYPES)
    from_location = models.ForeignKey(
        Location, on_delete=models.PROTECT, related_name="out_batches", blank=True, null=True
    )
    to_location = models.ForeignKey(
        Location, on_delete=models.PROTECT, related_name="in_batches", blank=True, null=True
    )
    timestamp = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-timestamp", "-id"]

    def __str__(self):
        return f"BATCH {self.id} {self.type} {self.timestamp:%Y-%m-%d %H:%M}"


class StockMoveLine(models.Model):
    batch = models.ForeignKey(StockMoveBatch, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="stock_move_lines")
    qty = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"Line#{self.id} {self.product.sku} x {self.qty} (batch {self.batch_id})"
