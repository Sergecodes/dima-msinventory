from collections import defaultdict
from decimal import Decimal
from django.db import transaction
from django.db.models import F
from inventory.models import InventoryLevel, StockMove, Product, Location, StockMoveBatch, StockMoveLine


class StockError(Exception):
    pass


def _get_level_for_update(product: Product, location: Location):
    # Lock row for update (create if missing with 0 on_hand)
    lvl, created = InventoryLevel.objects.select_for_update().get_or_create(
        product=product, location=location, defaults={"on_hand": Decimal("0")}
    )
    return lvl


@transaction.atomic
def apply_stock_move(*, type: str, product: Product, qty: Decimal,
                     from_location: Location | None, to_location: Location | None,
                     timestamp):
    if qty is None or qty <= 0:
        raise StockError("Quantity must be positive.")

    if type == StockMove.INBOUND:
        if not to_location:
            raise StockError("INBOUND moves require a destination (to_location).")
        to_lvl = _get_level_for_update(product, to_location)
        to_lvl.on_hand = F("on_hand") + qty
        to_lvl.save(update_fields=["on_hand"])

    elif type == StockMove.OUTBOUND:
        if not from_location:
            raise StockError("OUTBOUND moves require a source (from_location).")
        from_lvl = _get_level_for_update(product, from_location)
        # Check available
        from_lvl.refresh_from_db()
        if from_lvl.on_hand < qty:
            raise StockError("Insufficient stock at source location.")
        from_lvl.on_hand = F("on_hand") - qty
        from_lvl.save(update_fields=["on_hand"])

    elif type == StockMove.TRANSFER:
        if not from_location or not to_location:
            raise StockError("TRANSFER moves require both source and destination.")

        if getattr(from_location, "id", None) == getattr(to_location, "id", None):
            raise StockError("Source and destination locations must differ.")

        from_lvl = _get_level_for_update(product, from_location)
        to_lvl = _get_level_for_update(product, to_location)
        from_lvl.refresh_from_db()

        if from_lvl.on_hand < qty:
            raise StockError("Insufficient stock at source location for transfer.")

        from_lvl.on_hand = F("on_hand") - qty
        from_lvl.save(update_fields=["on_hand"])
        to_lvl.on_hand = F("on_hand") + qty
        to_lvl.save(update_fields=["on_hand"])
    else:
        raise StockError("Unknown move type.")

    # Create and return the persisted StockMove record
    move = StockMove.objects.create(
        type=type, product=product, qty=qty,
        from_location=from_location, to_location=to_location, timestamp=timestamp
    )
    return move


@transaction.atomic
def reverse_stock_move(move: StockMove):
    """Safely reverse (undo) a move; used by DELETE for StockMove."""
    qty = move.qty
    product = move.product

    if move.type == StockMove.INBOUND:
        # Undo: subtract from to_location
        if not move.to_location:
            raise StockError("Cannot reverse: missing destination.")

        to_lvl = _get_level_for_update(product, move.to_location)
        to_lvl.refresh_from_db()
        if to_lvl.on_hand < qty:
            raise StockError("Cannot reverse: would go negative at destination.")

        to_lvl.on_hand = F("on_hand") - qty
        to_lvl.save(update_fields=["on_hand"])

    elif move.type == StockMove.OUTBOUND:
        # Undo: add back to from_location
        if not move.from_location:
            raise StockError("Cannot reverse: missing source.")

        from_lvl = _get_level_for_update(product, move.from_location)
        from_lvl.on_hand = F("on_hand") + qty
        from_lvl.save(update_fields=["on_hand"])

    elif move.type == StockMove.TRANSFER:
        # Undo: move back from dest to source
        if not (move.from_location and move.to_location):
            raise StockError("Cannot reverse: missing locations.")
        to_lvl = _get_level_for_update(product, move.to_location)
        from_lvl = _get_level_for_update(product, move.from_location)
        to_lvl.refresh_from_db()
        if to_lvl.on_hand < qty:
            raise StockError("Cannot reverse: insufficient stock at destination.")

        to_lvl.on_hand = F("on_hand") - qty
        to_lvl.save(update_fields=["on_hand"])
        from_lvl.on_hand = F("on_hand") + qty
        from_lvl.save(update_fields=["on_hand"])
    else:
        raise StockError("Unknown move type.")

    # Delete original move
    move.delete()


def _group_lines_by_product(lines: list[dict]) -> dict[int, Decimal]:
    totals: dict[int, Decimal] = defaultdict(Decimal)
    for ln in lines:
        pid = ln["product"].id if isinstance(ln["product"], Product) else ln["product"]
        qty = Decimal(str(ln["qty"]))
        if qty <= 0:
            raise StockError("Line quantity must be positive.")
        totals[pid] = totals[pid] + qty
    return totals


@transaction.atomic
def apply_stock_batch_move(*, type: str,
                           from_location: Location | None,
                           to_location: Location | None,
                           timestamp,
                           lines: list[dict]):
    if type not in (StockMove.INBOUND, StockMove.OUTBOUND, StockMove.TRANSFER):
        raise StockError("Unknown move type.")
    if type == StockMove.INBOUND and not to_location:
        raise StockError("INBOUND requires a destination (to_location).")
    if type == StockMove.OUTBOUND and not from_location:
        raise StockError("OUTBOUND requires a source (from_location).")
    if type == StockMove.TRANSFER:
        if not (from_location and to_location):
            raise StockError("TRANSFER requires both source and destination.")
        if getattr(from_location, "id", None) == getattr(to_location, "id", None):
            raise StockError("Source and destination locations must differ.")
    if not lines:
        raise StockError("At least one line is required.")

    # Consolidate per-product to avoid race and multiple locks on same row
    totals = _group_lines_by_product(lines)

    # Lock rows we’ll touch
    levels_src = {}
    levels_dst = {}

    def lock_level(prod_id: int, loc: Location):
        prod = Product.objects.get(id=prod_id)
        lvl = _get_level_for_update(prod, loc)
        lvl.refresh_from_db()
        return lvl

    if type in (StockMove.OUTBOUND, StockMove.TRANSFER):
        for pid in totals:
            levels_src[pid] = lock_level(pid, from_location)  # type: ignore

    if type in (StockMove.INBOUND, StockMove.TRANSFER):
        for pid in totals:
            levels_dst[pid] = lock_level(pid, to_location)  # type: ignore

    # Feasibility checks (no negatives)
    if type in (StockMove.OUTBOUND, StockMove.TRANSFER):
        for pid, q in totals.items():
            if levels_src[pid].on_hand < q:
                raise StockError(f"Insufficient stock at source for product id={pid}.")

    # Apply
    if type == StockMove.INBOUND:
        for pid, q in totals.items():
            lvl = levels_dst[pid]
            lvl.on_hand = F("on_hand") + q
            lvl.save(update_fields=["on_hand"])
    elif type == StockMove.OUTBOUND:
        for pid, q in totals.items():
            lvl = levels_src[pid]
            lvl.on_hand = F("on_hand") - q
            lvl.save(update_fields=["on_hand"])
    else:  # TRANSFER
        for pid, q in totals.items():
            src = levels_src[pid]
            dst = levels_dst[pid]
            src.on_hand = F("on_hand") - q
            src.save(update_fields=["on_hand"])
            dst.on_hand = F("on_hand") + q
            dst.save(update_fields=["on_hand"])

    # Persist the batch + lines
    batch = StockMoveBatch.objects.create(
        type=type, from_location=from_location, to_location=to_location, timestamp=timestamp
    )
    StockMoveLine.objects.bulk_create([
        StockMoveLine(batch=batch, product=Product.objects.get(id=pid), qty=q)
        for pid, q in totals.items()
    ])
    return batch


@transaction.atomic
def reverse_stock_batch_move(batch: StockMoveBatch):
    lines = list(batch.lines.select_related("product"))
    if not lines:
        batch.delete()
        return

    totals = defaultdict(Decimal)
    for ln in lines:
        totals[ln.product_id] = totals[ln.product_id] + ln.qty

    # Lock needed rows
    levels_src = {}
    levels_dst = {}

    if batch.type == StockMoveBatch.INBOUND:
        for pid in totals:
            levels_dst[pid] = _get_level_for_update(ln.product if (ln := lines[0]) else Product.objects.get(id=pid),
                                                    batch.to_location)  # type: ignore
        # Check: we will subtract at destination
        for pid, q in totals.items():
            lvl = levels_dst[pid]
            lvl.refresh_from_db()
            if lvl.on_hand < q:
                raise StockError("Cannot reverse: would go negative at destination.")
        # Apply
        for pid, q in totals.items():
            lvl = levels_dst[pid]
            lvl.on_hand = F("on_hand") - q
            lvl.save(update_fields=["on_hand"])

    elif batch.type == StockMoveBatch.OUTBOUND:
        for pid in totals:
            levels_src[pid] = _get_level_for_update(ln.product if (ln := lines[0]) else Product.objects.get(id=pid),
                                                    batch.from_location)  # type: ignore
        for pid, q in totals.items():
            lvl = levels_src[pid]
            lvl.on_hand = F("on_hand") + q
            lvl.save(update_fields=["on_hand"])

    else:  # TRANSFER
        for pid in totals:
            levels_src[pid] = _get_level_for_update(ln.product if (ln := lines[0]) else Product.objects.get(id=pid),
                                                    batch.from_location)  # type: ignore
            levels_dst[pid] = _get_level_for_update(ln.product if (ln := lines[0]) else Product.objects.get(id=pid),
                                                    batch.to_location)  # type: ignore
        # Check: subtract from dest
        for pid, q in totals.items():
            lvl = levels_dst[pid]
            lvl.refresh_from_db()
            if lvl.on_hand < q:
                raise StockError("Cannot reverse: insufficient stock at destination.")

        # Apply reverse
        for pid, q in totals.items():
            dst = levels_dst[pid]
            src = levels_src[pid]
            dst.on_hand = F("on_hand") - q
            dst.save(update_fields=["on_hand"])
            src.on_hand = F("on_hand") + q
            src.save(update_fields=["on_hand"])

    batch.delete()
