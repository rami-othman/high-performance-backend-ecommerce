from decimal import Decimal
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from .models import Product


class TestDistributedLock:
    def __init__(self, acquired=True, status="ACQUIRED", on_enter=None):
        self.acquired = acquired
        self.status = status
        self.error = None
        self.on_enter = on_enter

    def __enter__(self):
        if self.on_enter is not None:
            self.on_enter()
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class ProductCachingTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = APIClient()
        self.product = Product.objects.create(
            name="Cached Product",
            description="Product used to verify cache headers.",
            price=Decimal("19.99"),
            stock=12,
        )

    def tearDown(self):
        cache.clear()

    def test_product_list_marks_first_response_miss_then_hit(self):
        url = reverse("product-list")

        with patch("products.views.redis_distributed_lock", return_value=TestDistributedLock()):
            first_response = self.client.get(url)
        second_response = self.client.get(url)

        self.assertEqual(first_response.status_code, status.HTTP_200_OK)
        self.assertEqual(second_response.status_code, status.HTTP_200_OK)
        self.assertEqual(first_response["X-Cache"], "MISS")
        self.assertEqual(first_response["X-Lock"], "ACQUIRED")
        self.assertEqual(second_response["X-Cache"], "HIT")
        self.assertEqual(first_response.data, second_response.data)

    def test_product_list_returns_waited_hit_when_another_worker_rebuilt_cache(self):
        url = reverse("product-list")
        cached_payload = [{"id": self.product.id, "name": self.product.name}]

        def seed_cache_after_wait():
            cache.set("products:list:v1", cached_payload)

        with patch(
            "products.views.redis_distributed_lock",
            return_value=TestDistributedLock(acquired=False, status="BUSY", on_enter=seed_cache_after_wait),
        ):
            response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["X-Cache"], "HIT")
        self.assertEqual(response["X-Lock"], "WAITED")
        self.assertEqual(response.data, cached_payload)

    def test_product_list_returns_busy_when_rebuild_lock_busy_and_cache_still_missing(self):
        url = reverse("product-list")

        with patch(
            "products.views.redis_distributed_lock",
            return_value=TestDistributedLock(acquired=False, status="BUSY"),
        ):
            response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.data["code"], "cache_rebuild_lock_busy")

    def test_product_detail_marks_first_response_miss_then_hit(self):
        url = reverse("product-detail", args=[self.product.id])

        with patch("products.views.redis_distributed_lock", return_value=TestDistributedLock()):
            first_response = self.client.get(url)
        second_response = self.client.get(url)

        self.assertEqual(first_response.status_code, status.HTTP_200_OK)
        self.assertEqual(second_response.status_code, status.HTTP_200_OK)
        self.assertEqual(first_response["X-Cache"], "MISS")
        self.assertEqual(first_response["X-Lock"], "ACQUIRED")
        self.assertEqual(second_response["X-Cache"], "HIT")
        self.assertEqual(first_response.data, second_response.data)

    def test_product_detail_returns_busy_when_rebuild_lock_busy_and_cache_still_missing(self):
        url = reverse("product-detail", args=[self.product.id])

        with patch(
            "products.views.redis_distributed_lock",
            return_value=TestDistributedLock(acquired=False, status="BUSY"),
        ):
            response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertEqual(response.data["code"], "cache_rebuild_lock_busy")
