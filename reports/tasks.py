from collections import defaultdict
from datetime import date
from decimal import Decimal

from celery import shared_task
from django.conf import settings
from django.db.models import Count, Sum
from django.utils import timezone

from orders.models import Order, OrderItem
from .models import DailySalesBatchRun, DailySalesReport


def parse_report_date(report_date):
    if report_date is None:
        return timezone.localdate()
    if isinstance(report_date, date):
        return report_date
    return date.fromisoformat(str(report_date))


def normalize_chunk_size(chunk_size):
    if chunk_size is None:
        chunk_size = getattr(settings, "DAILY_SALES_BATCH_CHUNK_SIZE", 100)
    chunk_size = int(chunk_size)
    if chunk_size < 1 or chunk_size > 1000:
        raise ValueError("chunk_size must be between 1 and 1000.")
    return chunk_size


def elapsed_ms(started_at, finished_at):
    return max(int((finished_at - started_at).total_seconds() * 1000), 0)


def decimal_or_zero(value):
    return value if value is not None else Decimal("0.00")


@shared_task(bind=True)
def process_daily_sales_report_task(self, report_date=None, batch_run_id=None, chunk_size=None):
    report_date = parse_report_date(report_date)
    chunk_size = normalize_chunk_size(chunk_size)
    started_at = timezone.now()
    batch_run = None

    try:
        if batch_run_id:
            batch_run = DailySalesBatchRun.objects.get(id=batch_run_id)
        else:
            batch_run = DailySalesBatchRun.objects.create(
                report_date=report_date,
                chunk_size=chunk_size,
            )

        batch_run.report_date = report_date
        batch_run.chunk_size = chunk_size
        batch_run.celery_task_id = self.request.id
        batch_run.status = DailySalesBatchRun.Status.STARTED
        batch_run.started_at = started_at
        batch_run.finished_at = None
        batch_run.duration_ms = None
        batch_run.error_message = ""
        batch_run.chunks_processed = 0
        batch_run.total_orders = 0
        batch_run.total_order_items = 0
        batch_run.total_quantity_sold = 0
        batch_run.total_sales = Decimal("0.00")
        batch_run.metadata = {
            "chunks": [],
            "algorithm": "keyset_pagination_by_order_id",
        }
        batch_run.save(
            update_fields=[
                "report_date",
                "chunk_size",
                "celery_task_id",
                "status",
                "started_at",
                "finished_at",
                "duration_ms",
                "error_message",
                "chunks_processed",
                "total_orders",
                "total_order_items",
                "total_quantity_sold",
                "total_sales",
                "metadata",
                "updated_at",
            ]
        )

        last_id = 0
        chunks = []
        product_quantities = defaultdict(int)
        total_orders = 0
        total_order_items = 0
        total_quantity_sold = 0
        total_sales = Decimal("0.00")

        while True:
            order_ids = list(
                Order.objects.filter(created_at__date=report_date, id__gt=last_id)
                .order_by("id")
                .values_list("id", flat=True)[:chunk_size]
            )

            if not order_ids:
                break

            chunk_started_at = timezone.now()
            order_totals = Order.objects.filter(id__in=order_ids).aggregate(
                orders_count=Count("id"),
                chunk_sales=Sum("total_price"),
            )
            item_totals = OrderItem.objects.filter(order_id__in=order_ids).aggregate(
                order_items_count=Count("id"),
                quantity_sold=Sum("quantity"),
            )
            product_rows = (
                OrderItem.objects.filter(order_id__in=order_ids)
                .values("product_id")
                .annotate(quantity_sold=Sum("quantity"))
            )

            orders_count = order_totals["orders_count"] or 0
            chunk_sales = decimal_or_zero(order_totals["chunk_sales"])
            order_items_count = item_totals["order_items_count"] or 0
            quantity_sold = item_totals["quantity_sold"] or 0

            for row in product_rows:
                product_quantities[row["product_id"]] += row["quantity_sold"] or 0

            chunk_finished_at = timezone.now()
            chunk_record = {
                "chunk_number": len(chunks) + 1,
                "first_order_id": order_ids[0],
                "last_order_id": order_ids[-1],
                "orders_count": orders_count,
                "order_items_count": order_items_count,
                "quantity_sold": quantity_sold,
                "chunk_sales": str(chunk_sales),
                "duration_ms": elapsed_ms(chunk_started_at, chunk_finished_at),
            }
            chunks.append(chunk_record)

            total_orders += orders_count
            total_order_items += order_items_count
            total_quantity_sold += quantity_sold
            total_sales += chunk_sales
            last_id = order_ids[-1]

            batch_run.chunks_processed = len(chunks)
            batch_run.total_orders = total_orders
            batch_run.total_order_items = total_order_items
            batch_run.total_quantity_sold = total_quantity_sold
            batch_run.total_sales = total_sales
            batch_run.metadata = {
                "chunks": chunks,
                "algorithm": "keyset_pagination_by_order_id",
            }
            batch_run.save(
                update_fields=[
                    "chunks_processed",
                    "total_orders",
                    "total_order_items",
                    "total_quantity_sold",
                    "total_sales",
                    "metadata",
                    "updated_at",
                ]
            )

        best_selling_product_id = None
        if product_quantities:
            best_selling_product_id = sorted(
                product_quantities.items(),
                key=lambda item: (-item[1], item[0]),
            )[0][0]

        report, _ = DailySalesReport.objects.update_or_create(
            date=report_date,
            defaults={
                "total_orders": total_orders,
                "total_order_items": total_order_items,
                "total_quantity_sold": total_quantity_sold,
                "total_sales": total_sales,
                "best_selling_product_id": best_selling_product_id,
            },
        )

        finished_at = timezone.now()
        batch_run.report = report
        batch_run.status = DailySalesBatchRun.Status.SUCCESS
        batch_run.finished_at = finished_at
        batch_run.duration_ms = elapsed_ms(started_at, finished_at)
        batch_run.error_message = ""
        batch_run.save(
            update_fields=[
                "report",
                "status",
                "finished_at",
                "duration_ms",
                "error_message",
                "updated_at",
            ]
        )

        return {
            "status": DailySalesBatchRun.Status.SUCCESS,
            "batch_run_id": batch_run.id,
            "report_id": report.id,
            "report_date": str(report_date),
            "chunk_size": chunk_size,
            "chunks_processed": batch_run.chunks_processed,
            "total_orders": total_orders,
            "total_order_items": total_order_items,
            "total_quantity_sold": total_quantity_sold,
            "total_sales": str(total_sales),
        }
    except Exception as exc:
        finished_at = timezone.now()
        if batch_run is not None:
            batch_run.status = DailySalesBatchRun.Status.FAILURE
            batch_run.finished_at = finished_at
            batch_run.duration_ms = elapsed_ms(started_at, finished_at)
            batch_run.error_message = str(exc)
            batch_run.save(
                update_fields=[
                    "status",
                    "finished_at",
                    "duration_ms",
                    "error_message",
                    "updated_at",
                ]
            )
        raise
