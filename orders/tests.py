from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from cart.models import Cart, CartItem
from payments.models import Payment
from products.models import Product
from .models import Order, OrderBackgroundTask


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

    def test_checkout_registers_background_tasks_after_commit(self):
        product = Product.objects.create(
            name="Async Product",
            price=Decimal("15.00"),
            stock=5,
        )
        cart = Cart.objects.create(user=self.user)
        CartItem.objects.create(cart=cart, product=product, quantity=1)

        with (
            patch("orders.views.CheckoutCapacityLimiter", return_value=TestCheckoutCapacityLimiter()),
            patch(
                "orders.views.generate_invoice_task.delay",
                return_value=SimpleNamespace(id="invoice-task-id"),
            ),
            patch(
                "orders.views.send_order_notification_task.delay",
                return_value=SimpleNamespace(id="notification-task-id"),
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            response = self.client.post(reverse("checkout"))

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data["background_tasks_dispatched"])

        order = Order.objects.get()
        task_rows = list(OrderBackgroundTask.objects.filter(order=order).order_by("task_name"))
        self.assertEqual(len(task_rows), 2)
        self.assertEqual(
            [(task.task_name, task.status, task.celery_task_id) for task in task_rows],
            [
                ("generate_invoice_task", OrderBackgroundTask.Status.QUEUED, "invoice-task-id"),
                ("send_order_notification_task", OrderBackgroundTask.Status.QUEUED, "notification-task-id"),
            ],
        )


class RaceConditionScriptTests(TestCase):
    def test_failure_metrics_separate_stock_failures_from_capacity_rejections(self):
        from scripts.race_condition_test import build_failure_metrics

        metrics = build_failure_metrics(
            [
                {
                    "status_code": 201,
                    "response": {"order_id": 1},
                    "success": True,
                },
                {
                    "status_code": 400,
                    "response": {"detail": "Not enough stock for Race Condition Test Product. Available stock: 0."},
                    "success": False,
                },
                {
                    "status_code": 429,
                    "response": {"code": "checkout_capacity_exceeded"},
                    "success": False,
                },
                {
                    "status_code": 500,
                    "response": {"detail": "Server error"},
                    "success": False,
                },
            ]
        )

        self.assertEqual(metrics["status_code_counts"], {"201": 1, "400": 1, "429": 1, "500": 1})
        self.assertEqual(
            metrics["error_code_counts"],
            {"checkout_capacity_exceeded": 1, "insufficient_stock": 1, "server_error": 1},
        )
        self.assertEqual(metrics["insufficient_stock_count"], 1)
        self.assertEqual(metrics["capacity_rejected_count"], 1)
        self.assertEqual(metrics["server_error_count"], 1)

    def test_build_summary_requires_stock_failures_not_capacity_failures(self):
        from scripts.race_condition_test import build_summary

        failure_metrics = {
            "status_code_counts": {"201": 5, "400": 15},
            "error_code_counts": {"insufficient_stock": 15},
            "insufficient_stock_count": 15,
            "capacity_rejected_count": 0,
            "server_error_count": 0,
        }
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
            failure_metrics=failure_metrics,
        )

        self.assertTrue(summary["passed"])
        self.assertEqual(summary["actual_successful_checkouts"], 5)
        self.assertEqual(summary["expected_successful_checkouts"], 5)
        self.assertEqual(summary["expected_failed_checkouts"], 15)
        self.assertEqual(summary["insufficient_stock_count"], 15)
        self.assertEqual(summary["capacity_rejected_count"], 0)
        self.assertEqual(summary["server_errors"], 0)
        self.assertFalse(summary["negative_stock"])
        self.assertFalse(summary["overselling"])

    def test_build_summary_fails_when_capacity_limiter_rejects_task1_requests(self):
        from scripts.race_condition_test import build_summary

        failure_metrics = {
            "status_code_counts": {"201": 5, "400": 10, "429": 5},
            "error_code_counts": {"insufficient_stock": 10, "checkout_capacity_exceeded": 5},
            "insufficient_stock_count": 10,
            "capacity_rejected_count": 5,
            "server_error_count": 0,
        }
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
            failure_metrics=failure_metrics,
        )

        self.assertFalse(summary["passed"])
        self.assertEqual(summary["capacity_rejected_count"], 5)


class CheckoutCapacityTestLimitOverrideTests(TestCase):
    @override_settings(
        DEBUG=True,
        CHECKOUT_MAX_CONCURRENT_REQUESTS=5,
        CHECKOUT_CAPACITY_TEST_LIMIT_OVERRIDE_ENABLED=True,
        CHECKOUT_CAPACITY_TEST_LIMIT_MAX=100,
    )
    def test_debug_header_can_raise_capacity_limit_for_race_condition_proof(self):
        from orders.views import get_checkout_capacity_limit

        request = SimpleNamespace(headers={"X-Race-Condition-Test-Capacity-Limit": "50"})

        self.assertEqual(get_checkout_capacity_limit(request), 50)

    @override_settings(
        DEBUG=False,
        CHECKOUT_MAX_CONCURRENT_REQUESTS=5,
        CHECKOUT_CAPACITY_TEST_LIMIT_OVERRIDE_ENABLED=True,
        CHECKOUT_CAPACITY_TEST_LIMIT_MAX=100,
    )
    def test_capacity_limit_override_is_disabled_when_debug_is_false(self):
        from orders.views import get_checkout_capacity_limit

        request = SimpleNamespace(headers={"X-Race-Condition-Test-Capacity-Limit": "50"})

        self.assertEqual(get_checkout_capacity_limit(request), 5)


class AsyncQueueScriptTests(TestCase):
    def test_build_summary_requires_successful_background_tasks_and_fast_checkout(self):
        from scripts.async_queue_test import build_summary

        summary = build_summary(
            checkout_status=201,
            checkout_duration_ms=100.0,
            background_tasks=[
                {
                    "task_name": "generate_invoice_task",
                    "status": "success",
                    "celery_task_id": "invoice-id",
                    "started_at": "2026-05-18T10:00:00+00:00",
                    "finished_at": "2026-05-18T10:00:01+00:00",
                    "duration_ms": 1000,
                },
                {
                    "task_name": "send_order_notification_task",
                    "status": "success",
                    "celery_task_id": "notification-id",
                    "started_at": "2026-05-18T10:00:00+00:00",
                    "finished_at": "2026-05-18T10:00:01+00:00",
                    "duration_ms": 1000,
                },
            ],
            order_exists=True,
            payment_exists=True,
            stock_reduced=True,
            checkout_returned_before_tasks_finished=True,
            server_error=False,
        )

        self.assertTrue(summary["passed"])
        self.assertEqual(summary["background_task_count"], 2)
        self.assertEqual(summary["successful_background_task_count"], 2)
        self.assertEqual(summary["total_background_duration_ms"], 2000)
