from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework import serializers

from orders.models import Order, OrderItem
from products.models import Product
from .models import DailySalesBatchRun, DailySalesReport
from .serializers import DailySalesBatchRequestSerializer
from .tasks import process_daily_sales_report_task


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
    DAILY_SALES_BATCH_CHUNK_SIZE=2,
)
class DailySalesBatchProcessingTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="batch-report-user",
            password="strong-password",
        )
        self.product_a = Product.objects.create(
            name="Batch Report Product A",
            price=Decimal("10.00"),
            stock=100,
        )
        self.product_b = Product.objects.create(
            name="Batch Report Product B",
            price=Decimal("5.00"),
            stock=100,
        )
        self.report_date = timezone.localdate() - timedelta(days=3)

    def create_paid_order(self, product, quantity, unit_price):
        order = Order.objects.create(
            user=self.user,
            total_price=unit_price * quantity,
            status=Order.Status.PAID,
        )
        OrderItem.objects.create(
            order=order,
            product=product,
            quantity=quantity,
            unit_price=unit_price,
            total_price=unit_price * quantity,
        )
        Order.objects.filter(id=order.id).update(
            created_at=timezone.make_aware(datetime.combine(self.report_date, time.min))
        )
        return order

    def test_batch_run_model_can_be_created(self):
        batch_run = DailySalesBatchRun.objects.create(
            report_date=self.report_date,
            chunk_size=50,
            metadata={"chunks": [], "algorithm": "keyset_pagination_by_order_id"},
        )

        self.assertEqual(batch_run.status, DailySalesBatchRun.Status.QUEUED)
        self.assertEqual(batch_run.report_date, self.report_date)
        self.assertEqual(batch_run.chunk_size, 50)
        self.assertEqual(batch_run.chunks_processed, 0)

    def test_request_serializer_rejects_invalid_chunk_sizes(self):
        for chunk_size in (0, 1001):
            serializer = DailySalesBatchRequestSerializer(data={"chunk_size": chunk_size})

            self.assertFalse(serializer.is_valid())
            self.assertIn("chunk_size", serializer.errors)

    def test_request_serializer_accepts_valid_optional_fields(self):
        serializer = DailySalesBatchRequestSerializer(
            data={"report_date": str(self.report_date), "chunk_size": 50}
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["report_date"], self.report_date)
        self.assertEqual(serializer.validated_data["chunk_size"], 50)

    def test_batch_task_processes_orders_in_multiple_chunks_and_updates_report(self):
        self.create_paid_order(self.product_a, quantity=1, unit_price=Decimal("10.00"))
        self.create_paid_order(self.product_a, quantity=2, unit_price=Decimal("10.00"))
        self.create_paid_order(self.product_b, quantity=4, unit_price=Decimal("5.00"))

        batch_run = DailySalesBatchRun.objects.create(
            report_date=self.report_date,
            chunk_size=2,
        )

        result = process_daily_sales_report_task.apply(
            kwargs={
                "report_date": str(self.report_date),
                "batch_run_id": batch_run.id,
                "chunk_size": 2,
            }
        ).get()

        batch_run.refresh_from_db()
        report = DailySalesReport.objects.get(date=self.report_date)

        self.assertEqual(result["status"], DailySalesBatchRun.Status.SUCCESS)
        self.assertEqual(batch_run.status, DailySalesBatchRun.Status.SUCCESS)
        self.assertEqual(batch_run.chunks_processed, 2)
        self.assertEqual(batch_run.total_orders, 3)
        self.assertEqual(batch_run.total_order_items, 3)
        self.assertEqual(batch_run.total_quantity_sold, 7)
        self.assertEqual(batch_run.total_sales, Decimal("50.00"))
        self.assertEqual(len(batch_run.metadata["chunks"]), 2)
        self.assertTrue(all(chunk["orders_count"] <= 2 for chunk in batch_run.metadata["chunks"]))
        self.assertEqual(batch_run.metadata["algorithm"], "keyset_pagination_by_order_id")
        self.assertEqual(batch_run.report, report)

        self.assertEqual(report.total_orders, batch_run.total_orders)
        self.assertEqual(report.total_order_items, batch_run.total_order_items)
        self.assertEqual(report.total_quantity_sold, batch_run.total_quantity_sold)
        self.assertEqual(report.total_sales, batch_run.total_sales)
        self.assertEqual(report.best_selling_product, self.product_b)

    def test_batch_task_rejects_invalid_chunk_size(self):
        with self.assertRaises(serializers.ValidationError):
            DailySalesBatchRequestSerializer(data={"chunk_size": 0}).is_valid(raise_exception=True)
