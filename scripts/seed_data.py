import os
from decimal import Decimal

import django


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from products.models import Product  # noqa: E402


PRODUCTS = [
    {
        "name": "Parallel Laptop",
        "description": "Developer laptop used for backend load testing examples.",
        "price": Decimal("1299.99"),
        "stock": 25,
    },
    {
        "name": "Redis Cache Node",
        "description": "Demo product representing a cache server.",
        "price": Decimal("199.99"),
        "stock": 50,
    },
    {
        "name": "PostgreSQL Storage Pack",
        "description": "Demo product representing durable relational storage.",
        "price": Decimal("349.50"),
        "stock": 40,
    },
    {
        "name": "Celery Worker Bundle",
        "description": "Demo product representing asynchronous background workers.",
        "price": Decimal("89.00"),
        "stock": 100,
    },
]


def run():
    for data in PRODUCTS:
        product, created = Product.objects.get_or_create(
            name=data["name"],
            defaults=data,
        )
        if not created:
            for field, value in data.items():
                setattr(product, field, value)
            product.save()
    print(f"Seeded {len(PRODUCTS)} products.")


if __name__ == "__main__":
    run()
