from decimal import Decimal

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from .models import Product


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

        first_response = self.client.get(url)
        second_response = self.client.get(url)

        self.assertEqual(first_response.status_code, status.HTTP_200_OK)
        self.assertEqual(second_response.status_code, status.HTTP_200_OK)
        self.assertEqual(first_response["X-Cache"], "MISS")
        self.assertEqual(second_response["X-Cache"], "HIT")
        self.assertEqual(first_response.data, second_response.data)

    def test_product_detail_marks_first_response_miss_then_hit(self):
        url = reverse("product-detail", args=[self.product.id])

        first_response = self.client.get(url)
        second_response = self.client.get(url)

        self.assertEqual(first_response.status_code, status.HTTP_200_OK)
        self.assertEqual(second_response.status_code, status.HTTP_200_OK)
        self.assertEqual(first_response["X-Cache"], "MISS")
        self.assertEqual(second_response["X-Cache"], "HIT")
        self.assertEqual(first_response.data, second_response.data)
