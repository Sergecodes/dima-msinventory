import pytest
from django.utils import timezone
from decimal import Decimal
from inventory.models import Product, Location, InventoryLevel, StockMove
from inventory.services.stock import apply_stock_move, StockError


@pytest.mark.django_db
def test_prevent_negative_outbound():
    p = Product.objects.create(sku="SKU1", name="A", cost=1, sales_price=2)
    loc = Location.objects.create(code="MAIN", name="Main")
    InventoryLevel.objects.create(product=p, location=loc, on_hand=Decimal("5"))
    # outbound more than on hand
    with pytest.raises(StockError):
        apply_stock_move(type=StockMove.OUTBOUND, product=p, qty=Decimal("6"), from_location=loc, to_location=None, timestamp=timezone.now())


@pytest.mark.django_db
def test_inbound_increases_stock():
    p = Product.objects.create(sku="SKU2", name="B", cost=1, sales_price=2)
    loc = Location.objects.create(code="MAIN", name="Main")
    apply_stock_move(type=StockMove.INBOUND, product=p, qty=Decimal("3"), from_location=None, to_location=loc, timestamp=timezone.now())
    lvl = InventoryLevel.objects.get(product=p, location=loc)
    assert lvl.on_hand == Decimal("3")
