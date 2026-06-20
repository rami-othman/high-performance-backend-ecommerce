from decimal import Decimal
from threading import Barrier, Thread
from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import cache
from django.contrib.auth import get_user_model
from django.db import connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from cart.models import Cart, CartItem
from payments.models import Payment
from products.cache_utils import (
    DAILY_SALES_REPORTS_LIST_CACHE_KEY,
    PRODUCT_LIST_CACHE_KEY,
    daily_sales_batch_run_detail_cache_key,
    product_detail_cache_key,
    remember_daily_sales_batch_run_cache,
)
from products.models import Product
from reports.models import DailySalesBatchRun
from .models import Order, OrderBackgroundTask, OrderItem


class TestCheckoutCapacityLimiter:
    acquired = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class TestDistributedLock:
    def __init__(self, acquired=True, status="ACQUIRED"):
        self.acquired = acquired
        self.status = status
        self.error = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class CheckoutTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="checkout-user",
            password="strong-password",
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.distributed_lock_patcher = patch(
            "orders.views.redis_distributed_lock",
            return_value=TestDistributedLock(),
        )
        self.distributed_lock_patcher.start()
        self.addCleanup(self.distributed_lock_patcher.stop)

    def tearDown(self):
        cache.clear()

    def test_checkout_creates_order_items_payment_updates_stock_clears_cart_and_dispatches_after_commit(self):
        product = Product.objects.create(
            name="Test Product",
            price=Decimal("12.50"),
            stock=10,
        )
        cart = Cart.objects.create(user=self.user)
        CartItem.objects.create(cart=cart, product=product, quantity=2)

        with (
            patch("orders.views.CheckoutCapacityLimiter", return_value=TestCheckoutCapacityLimiter()),
            patch(
                "orders.views.generate_invoice_task.delay",
                return_value=SimpleNamespace(id="invoice-task-id"),
            ) as invoice_delay,
            patch(
                "orders.views.send_order_notification_task.delay",
                return_value=SimpleNamespace(id="notification-task-id"),
            ) as notification_delay,
            self.captureOnCommitCallbacks(execute=True),
        ):
            response = self.client.post(reverse("checkout"))

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(OrderItem.objects.count(), 1)

        order = Order.objects.get()
        order_item = OrderItem.objects.get(order=order)
        product.refresh_from_db()
        cart.refresh_from_db()

        self.assertEqual(response.data["order_id"], order.id)
        self.assertEqual(response.data["total_price"], "25.00")
        self.assertEqual(response.data["status"], Order.Status.PAID)
        self.assertEqual(response.data["message"], "Checkout completed successfully.")
        self.assertEqual(product.stock, 8)
        self.assertEqual(cart.items.count(), 0)
        self.assertEqual(order_item.product, product)
        self.assertEqual(order_item.quantity, 2)
        self.assertEqual(order_item.unit_price, Decimal("12.50"))
        self.assertEqual(order_item.total_price, Decimal("25.00"))
        self.assertTrue(Payment.objects.filter(order=order, status=Payment.Status.COMPLETED).exists())
        invoice_delay.assert_called_once_with(
            order.id,
            background_task_id=OrderBackgroundTask.objects.get(task_name="generate_invoice_task").id,
        )
        notification_delay.assert_called_once_with(
            order.id,
            background_task_id=OrderBackgroundTask.objects.get(task_name="send_order_notification_task").id,
        )

    @override_settings(DEBUG=True)
    def test_debug_failure_after_stock_rolls_back_checkout_and_skips_post_commit_work(self):
        product = Product.objects.create(
            name="Rollback Product",
            price=Decimal("20.00"),
            stock=7,
        )
        cart = Cart.objects.create(user=self.user)
        CartItem.objects.create(cart=cart, product=product, quantity=3)

        cache.set(PRODUCT_LIST_CACHE_KEY, [{"id": product.id, "stock": product.stock}])
        cache.set(product_detail_cache_key(product.id), {"id": product.id, "stock": product.stock})
        self.client.raise_request_exception = False

        with (
            patch("orders.views.CheckoutCapacityLimiter", return_value=TestCheckoutCapacityLimiter()),
            patch("orders.views.invalidate_checkout_related_caches") as invalidate_caches,
            patch(
                "orders.views.generate_invoice_task.delay",
                return_value=SimpleNamespace(id="invoice-task-id"),
            ) as invoice_delay,
            patch(
                "orders.views.send_order_notification_task.delay",
                return_value=SimpleNamespace(id="notification-task-id"),
            ) as notification_delay,
            self.captureOnCommitCallbacks(execute=True) as callbacks,
        ):
            response = self.client.post(
                reverse("checkout"),
                HTTP_X_DEBUG_FAIL_CHECKOUT_AFTER_STOCK="1",
            )

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(callbacks, [])
        self.assertEqual(Order.objects.count(), 0)
        self.assertEqual(OrderItem.objects.count(), 0)
        self.assertEqual(Payment.objects.count(), 0)
        self.assertEqual(OrderBackgroundTask.objects.count(), 0)
        product.refresh_from_db()
        self.assertEqual(product.stock, 7)
        self.assertEqual(cart.items.count(), 1)
        self.assertEqual(cart.items.get(product=product).quantity, 3)
        invalidate_caches.assert_not_called()
        invoice_delay.assert_not_called()
        notification_delay.assert_not_called()
        self.assertIsNotNone(cache.get(PRODUCT_LIST_CACHE_KEY))
        self.assertIsNotNone(cache.get(product_detail_cache_key(product.id)))

    @override_settings(DEBUG=False, TESTING=False)
    def test_debug_failure_header_is_ignored_outside_debug_or_testing(self):
        product = Product.objects.create(
            name="Production Guard Product",
            price=Decimal("9.00"),
            stock=2,
        )
        cart = Cart.objects.create(user=self.user)
        CartItem.objects.create(cart=cart, product=product, quantity=1)

        with patch("orders.views.CheckoutCapacityLimiter", return_value=TestCheckoutCapacityLimiter()):
            response = self.client.post(
                reverse("checkout"),
                HTTP_X_DEBUG_FAIL_CHECKOUT_AFTER_STOCK="1",
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(Payment.objects.count(), 1)
        product.refresh_from_db()
        self.assertEqual(product.stock, 1)
        self.assertEqual(cart.items.count(), 0)

    def test_checkout_returns_busy_when_duplicate_submission_lock_is_held(self):
        product = Product.objects.create(
            name="Duplicate Lock Product",
            price=Decimal("10.00"),
            stock=3,
        )
        cart = Cart.objects.create(user=self.user)
        CartItem.objects.create(cart=cart, product=product, quantity=1)

        with (
            patch("orders.views.CheckoutCapacityLimiter", return_value=TestCheckoutCapacityLimiter()),
            patch("orders.views.redis_distributed_lock", return_value=TestDistributedLock(acquired=False, status="BUSY")),
        ):
            response = self.client.post(reverse("checkout"))

        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(response.data["code"], "checkout_lock_busy")
        self.assertEqual(Order.objects.count(), 0)

    def test_checkout_invalidates_product_and_report_caches_after_stock_changes(self):
        product = Product.objects.create(
            name="Cache Invalidated Product",
            price=Decimal("8.00"),
            stock=4,
        )
        batch_run = DailySalesBatchRun.objects.create(report_date="2026-06-19", chunk_size=10)
        cart = Cart.objects.create(user=self.user)
        CartItem.objects.create(cart=cart, product=product, quantity=1)

        cache.set(PRODUCT_LIST_CACHE_KEY, [{"id": product.id, "stock": product.stock}])
        cache.set(product_detail_cache_key(product.id), {"id": product.id, "stock": product.stock})
        cache.set(DAILY_SALES_REPORTS_LIST_CACHE_KEY, [{"date": "2026-06-19"}])
        cache.set(daily_sales_batch_run_detail_cache_key(batch_run.id), {"id": batch_run.id})
        remember_daily_sales_batch_run_cache(batch_run.id)

        with (
            patch("orders.views.CheckoutCapacityLimiter", return_value=TestCheckoutCapacityLimiter()),
            patch("orders.views.generate_invoice_task.delay", return_value=SimpleNamespace(id="invoice-task-id")),
            patch(
                "orders.views.send_order_notification_task.delay",
                return_value=SimpleNamespace(id="notification-task-id"),
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            response = self.client.post(reverse("checkout"))

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(cache.get(PRODUCT_LIST_CACHE_KEY))
        self.assertIsNone(cache.get(product_detail_cache_key(product.id)))
        self.assertIsNone(cache.get(DAILY_SALES_REPORTS_LIST_CACHE_KEY))
        self.assertIsNone(cache.get(daily_sales_batch_run_detail_cache_key(batch_run.id)))

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

    def test_classify_failure_recognizes_current_out_of_stock_error_response(self):
        from scripts.race_condition_test import classify_failure

        self.assertEqual(classify_failure(400, {"error": "Out of stock"}), "insufficient_stock")

    def test_race_condition_script_issues_tokens_locally_without_auth_endpoint(self):
        from scripts.race_condition_test import issue_access_token

        user = get_user_model().objects.create_user(
            username="race-token-user",
            password="RaceTestPassword123!",
        )

        with patch("scripts.race_condition_test.post_json") as post_json:
            token = issue_access_token(user)

        self.assertIsInstance(token, str)
        self.assertGreater(len(token), 20)
        post_json.assert_not_called()

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


class ResourceCapacityScriptTests(TestCase):
    def test_capacity_rejection_recognizes_current_busy_response(self):
        from scripts.resource_capacity_test import is_capacity_rejected

        self.assertTrue(is_capacity_rejected(429, {"detail": "Busy"}))
        self.assertTrue(is_capacity_rejected(429, {"code": "checkout_capacity_exceeded"}))
        self.assertFalse(is_capacity_rejected(400, {"detail": "Busy"}))

    def test_resource_capacity_script_issues_tokens_locally_without_auth_endpoint(self):
        from scripts.resource_capacity_test import issue_access_token

        user = get_user_model().objects.create_user(
            username="capacity-token-user",
            password="CapacityTestPassword123!",
        )

        with patch("scripts.resource_capacity_test.post_json") as post_json:
            token = issue_access_token(user)

        self.assertIsInstance(token, str)
        self.assertGreater(len(token), 20)
        post_json.assert_not_called()


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class ConcurrentCheckoutTransactionTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        cache.clear()
        self.distributed_lock_patcher = patch(
            "orders.views.redis_distributed_lock",
            return_value=TestDistributedLock(),
        )
        self.distributed_lock_patcher.start()
        self.addCleanup(self.distributed_lock_patcher.stop)

    def tearDown(self):
        cache.clear()

    def test_concurrent_checkout_does_not_oversell_shared_stock(self):
        product = Product.objects.create(
            name="Concurrent Product",
            price=Decimal("11.00"),
            stock=1,
        )
        User = get_user_model()
        users = []
        for index in range(2):
            user = User.objects.create_user(
                username=f"concurrent-user-{index}",
                password="strong-password",
            )
            cart = Cart.objects.create(user=user)
            CartItem.objects.create(cart=cart, product=product, quantity=1)
            users.append(user)

        barrier = Barrier(len(users))
        results = []

        def checkout(user):
            try:
                client = APIClient()
                client.force_authenticate(user=user)
                barrier.wait(timeout=5)
                with patch("orders.views.CheckoutCapacityLimiter", return_value=TestCheckoutCapacityLimiter()):
                    response = client.post(reverse("checkout"))
                results.append(response.status_code)
            finally:
                connections.close_all()

        threads = [Thread(target=checkout, args=(user,)) for user in users]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        connections.close_all()

        self.assertEqual(sorted(results), [status.HTTP_201_CREATED, status.HTTP_400_BAD_REQUEST])
        product.refresh_from_db()
        self.assertEqual(product.stock, 0)
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(OrderItem.objects.filter(product=product).count(), 1)
        self.assertEqual(Payment.objects.count(), 1)


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


class AcidTransactionScriptTests(TestCase):
    def test_build_result_requires_success_and_rollback_cases_to_pass(self):
        from scripts.acid_transaction_test import build_result

        result = build_result(
            success_case={"passed": True},
            rollback_case={"passed": False},
            initial_state={"orders": 0, "payments": 0},
            final_state={"orders": 1, "payments": 1},
        )

        self.assertEqual(result["result"], "FAILED")
        self.assertFalse(result["passed"])
        self.assertEqual(result["success_case"], {"passed": True})
        self.assertEqual(result["rollback_case"], {"passed": False})


class StressTestScriptTests(TestCase):
    def test_calculate_timing_summary_includes_average_p95_and_rps(self):
        from scripts.stress_test_100_users import calculate_timing_summary

        summary = calculate_timing_summary(
            [
                {"operation": "login", "duration_ms": 10.0, "status_code": 200},
                {"operation": "login", "duration_ms": 30.0, "status_code": 200},
                {"operation": "checkout", "duration_ms": 50.0, "status_code": 201},
                {"operation": "checkout", "duration_ms": 70.0, "status_code": 500},
            ],
            total_duration_seconds=2.0,
        )

        self.assertEqual(summary["total_requests"], 4)
        self.assertEqual(summary["average_response_time_ms"], 40.0)
        self.assertEqual(summary["min_response_time_ms"], 10.0)
        self.assertEqual(summary["max_response_time_ms"], 70.0)
        self.assertEqual(summary["p95_response_time_ms"], 70.0)
        self.assertEqual(summary["requests_per_second"], 2.0)
        self.assertEqual(summary["error_rate"], 0.25)
        self.assertEqual(summary["status_code_distribution"], {"200": 2, "201": 1, "500": 1})
        self.assertEqual(summary["per_operation"]["login"]["count"], 2)
        self.assertEqual(summary["per_operation"]["checkout"]["errors"], 1)

    def test_build_data_integrity_summary_detects_overselling_and_count_mismatch(self):
        from scripts.stress_test_100_users import build_data_integrity_summary

        summary = build_data_integrity_summary(
            initial_stock_by_product={1: 5, 2: 5},
            final_stock_by_product={1: 1, 2: -1},
            sold_quantity_by_product={1: 4, 2: 7},
            successful_checkout_count=10,
            order_count=9,
            payment_count=10,
        )

        self.assertFalse(summary["passed"])
        self.assertTrue(summary["negative_stock"])
        self.assertTrue(summary["overselling"])
        self.assertFalse(summary["orders_match_successful_checkouts"])
        self.assertTrue(summary["payments_match_successful_checkouts"])

    def test_report_operation_status_rules_require_admin_success_but_allow_regular_forbidden(self):
        from scripts.stress_test_100_users import allowed_statuses_for_operation, build_summary

        self.assertEqual(allowed_statuses_for_operation("get_daily_sales_report_as_regular_user"), {200, 403})
        self.assertEqual(allowed_statuses_for_operation("get_daily_sales_report_as_admin"), {200})

        summary = build_summary(
            total_users=100,
            user_results=[{"checkout_success": True, "success": True} for _ in range(100)],
            request_records=[],
            failed_requests=[],
            timing_summary={
                "total_requests": 0,
                "average_response_time_ms": 0,
                "min_response_time_ms": 0,
                "max_response_time_ms": 0,
                "p95_response_time_ms": 0,
                "requests_per_second": 0,
                "error_rate": 0,
                "status_code_distribution": {},
            },
            data_integrity={"passed": True},
            report_operations_passed=False,
        )

        self.assertFalse(summary["passed"])
