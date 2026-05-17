from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from cart.models import Cart, CartItem
from payments.models import Payment
from products.models import Product
from .models import Order


class TestCheckoutCapacityLimiter:
    acquired = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class CheckoutTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="checkout-user",
            password="strong-password",
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_checkout_creates_order_updates_stock_clears_cart_and_creates_payment(self):
        product = Product.objects.create(
            name="Test Product",
            price=Decimal("12.50"),
            stock=10,
        )
        cart = Cart.objects.create(user=self.user)
        CartItem.objects.create(cart=cart, product=product, quantity=2)

        with patch("orders.views.CheckoutCapacityLimiter", return_value=TestCheckoutCapacityLimiter()):
            response = self.client.post(reverse("checkout"))

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Order.objects.count(), 1)

        order = Order.objects.get()
        product.refresh_from_db()
        cart.refresh_from_db()

        self.assertEqual(response.data["order_id"], order.id)
        self.assertEqual(response.data["total_price"], "25.00")
        self.assertEqual(response.data["status"], Order.Status.PAID)
        self.assertEqual(response.data["message"], "Checkout completed successfully.")
        self.assertEqual(product.stock, 8)
        self.assertEqual(cart.items.count(), 0)
        self.assertTrue(Payment.objects.filter(order=order, status=Payment.Status.COMPLETED).exists())


class RaceConditionScriptTests(TestCase):
    def test_build_summary_detects_no_overselling_for_expected_result(self):
        from scripts.race_condition_test import build_summary

        summary = build_summary(
            initial_stock=5,
            user_count=20,
            quantity=1,
            success_count=5,
            failure_count=15,
            final_stock=0,
            successful_order_count=5,
            total_sold_quantity=5,
            payment_count=5,
        )

        self.assertTrue(summary["passed"])
        self.assertEqual(summary["expected_successful_checkouts"], 5)
        self.assertEqual(summary["expected_failed_checkouts"], 15)
        self.assertFalse(summary["negative_stock"])
        self.assertFalse(summary["overselling"])
