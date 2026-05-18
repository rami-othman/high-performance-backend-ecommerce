from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from .models import PerformanceLog


class FakeRedis:
    def __init__(self):
        self.values = {}

    def incr(self, key):
        self.values[key] = int(self.values.get(key, 0)) + 1
        return self.values[key]

    def decr(self, key):
        self.values[key] = int(self.values.get(key, 0)) - 1
        return self.values[key]

    def expire(self, key, ttl_seconds):
        return True

    def get(self, key):
        value = self.values.get(key)
        if value is None:
            return None
        return str(value).encode("utf-8")

    def set(self, key, value):
        self.values[key] = int(value)
        return True

    def delete(self, *keys):
        for key in keys:
            self.values.pop(key, None)
        return len(keys)


class CheckoutCapacityLimiterTests(SimpleTestCase):
    def test_limiter_denies_requests_above_configured_limit_and_releases_slot(self):
        from performance.capacity_limiter import CheckoutCapacityLimiter, get_checkout_capacity_metrics

        redis_client = FakeRedis()
        key = "test:checkout:active"

        with CheckoutCapacityLimiter(redis_client=redis_client, key=key, limit=1, ttl_seconds=30) as first:
            self.assertTrue(first.acquired)
            with CheckoutCapacityLimiter(redis_client=redis_client, key=key, limit=1, ttl_seconds=30) as second:
                self.assertFalse(second.acquired)

            metrics = get_checkout_capacity_metrics(redis_client=redis_client, key=key, limit=1)
            self.assertEqual(metrics["active_checkouts"], 1)
            self.assertEqual(metrics["max_observed_active_checkouts"], 1)

        metrics = get_checkout_capacity_metrics(redis_client=redis_client, key=key, limit=1)
        self.assertEqual(metrics["active_checkouts"], 0)


class ResourceCapacityScriptTests(SimpleTestCase):
    def test_build_summary_requires_limit_respected_and_capacity_rejections(self):
        from scripts.resource_capacity_test import build_summary

        summary = build_summary(
            configured_limit=5,
            user_count=20,
            initial_stock=100,
            quantity=1,
            success_count=5,
            capacity_rejected_count=15,
            other_failed_count=0,
            server_error_count=0,
            final_stock=95,
            total_sold_quantity=5,
            max_observed_active_checkouts=5,
            delay_seconds=1.0,
        )

        self.assertTrue(summary["passed"])
        self.assertTrue(summary["limit_respected"])
        self.assertTrue(summary["overlap_observed"])
        self.assertEqual(summary["capacity_rejected_count"], 15)
        self.assertEqual(summary["server_errors"], 0)

    def test_build_summary_fails_when_server_processes_checkouts_sequentially(self):
        from scripts.resource_capacity_test import build_summary

        summary = build_summary(
            configured_limit=5,
            user_count=20,
            initial_stock=100,
            quantity=1,
            success_count=20,
            capacity_rejected_count=0,
            other_failed_count=0,
            server_error_count=0,
            final_stock=80,
            total_sold_quantity=20,
            max_observed_active_checkouts=1,
            delay_seconds=1.0,
        )

        self.assertFalse(summary["passed"])
        self.assertFalse(summary["overlap_observed"])


class SystemEndpointTests(TestCase):
    @override_settings(SERVER_NAME="unit-test-server")
    def test_health_endpoint_returns_status_and_server_identity(self):
        initial_log_count = PerformanceLog.objects.count()

        response = self.client.get(reverse("health"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        self.assertEqual(response.json()["server_name"], "unit-test-server")
        self.assertIn("hostname", response.json())
        self.assertIn("timestamp", response.json())
        self.assertEqual(PerformanceLog.objects.count(), initial_log_count)

    @override_settings(SERVER_NAME="unit-test-server")
    def test_server_info_endpoint_returns_server_identity_and_header(self):
        initial_log_count = PerformanceLog.objects.count()

        response = self.client.get(reverse("server-info"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["server_name"], "unit-test-server")
        self.assertEqual(response.headers["X-Backend-Server"], "unit-test-server")
        self.assertIn("hostname", response.json())
        self.assertIn("process_id", response.json())
        self.assertIn("thread_id", response.json())
        self.assertIn("timestamp", response.json())
        self.assertEqual(PerformanceLog.objects.count(), initial_log_count)
