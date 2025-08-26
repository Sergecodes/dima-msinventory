import csv
from decimal import Decimal
from django.core.management.base import BaseCommand, CommandError
from inventory.models import Product


class Command(BaseCommand):
    help = "Import products from a CSV file (columns like: Name, Internal Reference, Barcode, Cost, Sales Price, " \
           "Product Category)"

    def add_arguments(self, parser):
        parser.add_argument("csv_path", type=str, help="Path to product-template.csv")

    def handle(self, *args, **options):
        path = options["csv_path"]
        created = 0
        updated = 0
        try:
            with open(path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    sku = (row.get("Internal Reference") or "").strip() or None
                    name = (row.get("Name") or "").strip() or None
                    if not sku or not name:
                        self.stdout.write(self.style.WARNING(f"Skipping row without sku/name: {row}"))
                        continue
                    obj, is_created = Product.objects.update_or_create(
                        sku=sku,
                        defaults={
                            "name": name,
                            "barcode": (row.get("Barcode") or "").strip() or None,
                            "category": (row.get("Product Category") or "").strip() or None,
                            "cost": Decimal(str(row.get("Cost") or "0") or "0"),
                            "sales_price": Decimal(str(row.get("Sales Price") or "0") or "0"),
                            "is_active": True,
                        },
                    )
                    created += int(is_created)
                    updated += int(not is_created)
        except FileNotFoundError:
            raise CommandError(f"File not found: {path}")

        self.stdout.write(self.style.SUCCESS(f"Imported products. created={created}, updated={updated}"))
