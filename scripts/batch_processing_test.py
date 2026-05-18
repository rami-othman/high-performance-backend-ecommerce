import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, time as datetime_time
from decimal import Decimal
from math import ceil
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django
from django.apps import apps

if not apps.ready:
    django.setup()

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from orders.models import Order, OrderItem
from products.models import Product
from reports.models import DailySalesBatchRun, DailySalesReport


DEFAULT_BASE_URL = "http://127.0.0.1:8000"
BATCH_USERNAME_PREFIX = "batch_processing_user_"
BATCH_PASSWORD = "BatchProcessingPassword123!"
PRODUCT_NAME_PREFIX = "Batch Processing Test Product"
CELERY_WORKER_MESSAGE = (
    "Start the Celery worker with docker compose up or celery -A config worker --loglevel=info"
)


class BatchProcessingTestError(Exception):
    pass


def parse_args():
    parser = argparse.ArgumentParser(description="Task 4 batch processing proof for daily sales reports.")
    parser.add_argument(
        "--base-url",
        default=os.getenv("API_BASE_URL", DEFAULT_BASE_URL),
        help="Django API base URL. Defaults to API_BASE_URL or http://127.0.0.1:8000.",
    )
    parser.add_argument(
        "--orders",
        type=int,
        default=getattr(settings, "DAILY_SALES_BATCH_TEST_ORDER_COUNT", 250),
        help="Number of test orders to generate.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=getattr(settings, "DAILY_SALES_BATCH_TEST_CHUNK_SIZE", 50),
        help="Chunk size requested from the batch API.",
    )
    parser.add_argument("--timeout", type=float, default=30.0, help="Seconds to wait for Celery success.")
    parser.add_argument(
        "--report-date",
        default="2001-01-15",
        help="Isolated report date for generated orders.",
    )
    return parser.parse_args()


def normalize_base_url(base_url):
    return base_url.rstrip("/")


def parse_json_body(body):
    if not body:
        return {}
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return {"raw_body": body}


def post_json(url, payload, headers=None, timeout=20):
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            **(headers or {}),
        },
        method="POST",
    )
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            return response.status, parse_json_body(body), duration_ms
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        return exc.code, parse_json_body(body), duration_ms
    except urllib.error.URLError as exc:
        raise BatchProcessingTestError(
            f"Could not connect to the Django API at {url}. "
            "Start the server and check API_BASE_URL or --base-url."
        ) from exc


def get_status(url, timeout=5):
    request = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status
    except urllib.error.URLError as exc:
        raise BatchProcessingTestError(
            f"Could not connect to the Django API at {url}. "
            "Start the server and check API_BASE_URL or --base-url."
        ) from exc


def cleanup_previous_test_data(report_date):
    User = get_user_model()
    User.objects.filter(username__startswith=BATCH_USERNAME_PREFIX).delete()
    DailySalesBatchRun.objects.filter(report_date=report_date).delete()
    DailySalesReport.objects.filter(date=report_date).delete()

    for product in Product.objects.filter(name__startswith=PRODUCT_NAME_PREFIX):
        if not OrderItem.objects.filter(product=product).exists():
            product.delete()


def setup_test_data(order_count, report_date):
    if order_count < 1:
        raise BatchProcessingTestError("--orders must be at least 1.")

    try:
        with transaction.atomic():
            cleanup_previous_test_data(report_date)
            User = get_user_model()
            admin_user = User.objects.create_user(
                username=f"{BATCH_USERNAME_PREFIX}admin",
                email="batch-processing-admin@example.com",
                password=BATCH_PASSWORD,
                is_staff=True,
                is_superuser=True,
            )
            products = [
                Product.objects.create(
                    name=f"{PRODUCT_NAME_PREFIX} {index}",
                    description="Temporary product used by scripts/batch_processing_test.py.",
                    price=price,
                    stock=10000,
                )
                for index, price in enumerate(
                    [Decimal("10.00"), Decimal("15.50"), Decimal("20.00")],
                    start=1,
                )
            ]

            created_order_ids = []
            expected_total_sales = Decimal("0.00")
            expected_quantity = 0
            expected_order_items = 0
            created_at = timezone.make_aware(datetime.combine(report_date, datetime_time(hour=10)))

            for index in range(order_count):
                product = products[index % len(products)]
                quantity = (index % 5) + 1
                total_price = product.price * quantity
                order = Order.objects.create(
                    user=admin_user,
                    total_price=total_price,
                    status=Order.Status.PAID,
                )
                OrderItem.objects.create(
                    order=order,
                    product=product,
                    quantity=quantity,
                    unit_price=product.price,
                    total_price=total_price,
                )
                created_order_ids.append(order.id)
                expected_total_sales += total_price
                expected_quantity += quantity
                expected_order_items += 1

            Order.objects.filter(id__in=created_order_ids).update(created_at=created_at)

            return {
                "admin_user": admin_user,
                "product_ids": [product.id for product in products],
                "order_ids": created_order_ids,
                "expected_total_sales": expected_total_sales,
                "expected_quantity": expected_quantity,
                "expected_order_items": expected_order_items,
            }
    except Exception as exc:
        raise BatchProcessingTestError(f"Database setup failed: {exc}") from exc


def obtain_token(base_url, username):
    status_code, payload, _ = post_json(
        f"{base_url}/api/auth/token/",
        {"username": username, "password": BATCH_PASSWORD},
        timeout=15,
    )
    if status_code != 200 or "access" not in payload:
        raise BatchProcessingTestError(
            "JWT login failed. Check that the Django API is running and that "
            f"API_BASE_URL/--base-url points to the right server. User: {username}. "
            f"Status: {status_code}. Response: {payload}"
        )
    return payload["access"]


def trigger_batch_job(base_url, token, report_date, chunk_size):
    return post_json(
        f"{base_url}/api/reports/daily-sales/run/",
        {"report_date": str(report_date), "chunk_size": chunk_size},
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )


def wait_for_batch_success(batch_run_id, timeout_seconds):
    deadline = time.monotonic() + timeout_seconds
    last_state = None
    while time.monotonic() < deadline:
        batch_run = DailySalesBatchRun.objects.select_related("report").get(id=batch_run_id)
        last_state = serialize_batch_run(batch_run)
        if batch_run.status in {DailySalesBatchRun.Status.SUCCESS, DailySalesBatchRun.Status.FAILURE}:
            return batch_run
        time.sleep(0.5)

    raise BatchProcessingTestError(
        "Timed out waiting for DailySalesBatchRun to reach success. "
        f"{CELERY_WORKER_MESSAGE}. Last batch state: {last_state}"
    )


def serialize_batch_run(batch_run):
    return {
        "id": batch_run.id,
        "report_date": str(batch_run.report_date),
        "report_id": batch_run.report_id,
        "celery_task_id": batch_run.celery_task_id,
        "status": batch_run.status,
        "chunk_size": batch_run.chunk_size,
        "chunks_processed": batch_run.chunks_processed,
        "total_orders": batch_run.total_orders,
        "total_order_items": batch_run.total_order_items,
        "total_quantity_sold": batch_run.total_quantity_sold,
        "total_sales": str(batch_run.total_sales),
        "started_at": batch_run.started_at.isoformat() if batch_run.started_at else None,
        "finished_at": batch_run.finished_at.isoformat() if batch_run.finished_at else None,
        "duration_ms": batch_run.duration_ms,
        "metadata": batch_run.metadata,
        "error_message": batch_run.error_message,
    }


def serialize_report(report):
    return {
        "id": report.id,
        "date": str(report.date),
        "total_orders": report.total_orders,
        "total_order_items": report.total_order_items,
        "total_quantity_sold": report.total_quantity_sold,
        "total_sales": str(report.total_sales),
        "best_selling_product_id": report.best_selling_product_id,
    }


def build_summary(
    trigger_status,
    expected_orders,
    chunk_size,
    expected_total_sales,
    expected_quantity,
    expected_order_items,
    batch_run,
    report,
):
    expected_chunks = ceil(expected_orders / chunk_size)
    chunks = batch_run.metadata.get("chunks", [])
    all_chunks_within_size = all(chunk.get("orders_count", 0) <= chunk_size for chunk in chunks)
    report_totals_match = (
        report is not None
        and report.total_orders == batch_run.total_orders
        and report.total_order_items == batch_run.total_order_items
        and report.total_quantity_sold == batch_run.total_quantity_sold
        and report.total_sales == batch_run.total_sales
    )
    total_sales_correct = batch_run.total_sales == expected_total_sales
    passed = (
        trigger_status == 202
        and batch_run.status == DailySalesBatchRun.Status.SUCCESS
        and bool(batch_run.celery_task_id)
        and batch_run.chunks_processed == expected_chunks
        and batch_run.total_orders == expected_orders
        and batch_run.total_order_items == expected_order_items
        and batch_run.total_quantity_sold == expected_quantity
        and total_sales_correct
        and report is not None
        and report_totals_match
        and len(chunks) == batch_run.chunks_processed
        and all_chunks_within_size
    )

    return {
        "api_trigger_status": trigger_status,
        "generated_test_orders": expected_orders,
        "chunk_size": chunk_size,
        "expected_chunks": expected_chunks,
        "actual_chunks_processed": batch_run.chunks_processed,
        "total_orders_in_batch": batch_run.total_orders,
        "total_order_items": batch_run.total_order_items,
        "total_quantity_sold": batch_run.total_quantity_sold,
        "expected_total_quantity_sold": expected_quantity,
        "total_sales": str(batch_run.total_sales),
        "expected_total_sales": str(expected_total_sales),
        "total_sales_correct": total_sales_correct,
        "daily_sales_report_created": report is not None,
        "report_totals_match": report_totals_match,
        "celery_task_id_present": bool(batch_run.celery_task_id),
        "metadata_chunk_count": len(chunks),
        "all_chunks_within_chunk_size": all_chunks_within_size,
        "batch_status": batch_run.status,
        "passed": passed,
    }


def save_results(result):
    results_dir = BASE_DIR / "results" / "batch_processing"
    results_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    timestamped_path = results_dir / f"batch_processing_task4_{timestamp}.json"
    latest_path = results_dir / "batch_processing_task4_latest.json"

    for path in (timestamped_path, latest_path):
        path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")

    return timestamped_path, latest_path


def print_summary(report_date, summary):
    print("\nTask 4 - Batch Processing Proof\n")
    print(f"Report date: {report_date}")
    print(f"Generated test orders: {summary['generated_test_orders']}")
    print(f"Chunk size: {summary['chunk_size']}")
    print(f"Expected chunks: {summary['expected_chunks']}")
    print(f"Actual chunks processed: {summary['actual_chunks_processed']}")
    print(f"Total orders in batch: {summary['total_orders_in_batch']}")
    print(f"Total quantity sold: {summary['total_quantity_sold']}")
    print(f"Total sales: {summary['total_sales']}")
    print(f"Total sales correct: {'Yes' if summary['total_sales_correct'] else 'No'}")
    print(f"DailySalesReport created: {'Yes' if summary['daily_sales_report_created'] else 'No'}")
    print(f"Celery task ID present: {'Yes' if summary['celery_task_id_present'] else 'No'}")
    print(f"All chunks within chunk size: {'Yes' if summary['all_chunks_within_chunk_size'] else 'No'}")
    print(f"Batch status: {summary['batch_status']}")
    print(f"Result: {'PASSED' if summary['passed'] else 'FAILED'}")


def main():
    args = parse_args()
    base_url = normalize_base_url(args.base_url)
    report_date = date.fromisoformat(args.report_date)

    try:
        get_status(f"{base_url}/api/health/")
        setup = setup_test_data(args.orders, report_date)
        token = obtain_token(base_url, setup["admin_user"].username)
        trigger_status, trigger_payload, trigger_duration_ms = trigger_batch_job(
            base_url,
            token,
            report_date,
            args.chunk_size,
        )

        if trigger_status != 202:
            raise BatchProcessingTestError(
                f"Batch API did not return 202. Status: {trigger_status}. Response: {trigger_payload}"
            )
        batch_run_id = trigger_payload.get("batch_run_id")
        celery_task_id = trigger_payload.get("celery_task_id")
        if not batch_run_id or not celery_task_id:
            raise BatchProcessingTestError(f"Batch API response was missing IDs: {trigger_payload}")

        batch_run = wait_for_batch_success(batch_run_id, args.timeout)
        if batch_run.status == DailySalesBatchRun.Status.FAILURE:
            raise BatchProcessingTestError(
                f"Batch run failed. Error: {batch_run.error_message}. {CELERY_WORKER_MESSAGE}"
            )
        report = DailySalesReport.objects.filter(date=report_date).first()
        summary = build_summary(
            trigger_status=trigger_status,
            expected_orders=args.orders,
            chunk_size=args.chunk_size,
            expected_total_sales=setup["expected_total_sales"],
            expected_quantity=setup["expected_quantity"],
            expected_order_items=setup["expected_order_items"],
            batch_run=batch_run,
            report=report,
        )
        result = {
            "api_base_url": base_url,
            "report_date": str(report_date),
            "product_ids": setup["product_ids"],
            "order_count": len(setup["order_ids"]),
            "api_trigger": {
                "status": trigger_status,
                "duration_ms": trigger_duration_ms,
                "response": trigger_payload,
            },
            "summary": summary,
            "batch_run": serialize_batch_run(batch_run),
            "daily_sales_report": serialize_report(report) if report else None,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        timestamped_path, latest_path = save_results(result)
        print_summary(report_date, summary)
        print(f"\nSaved latest result: {latest_path}")
        print(f"Saved timestamped result: {timestamped_path}")
        return 0 if summary["passed"] else 1
    except BatchProcessingTestError as exc:
        print(f"\nTask 4 batch processing proof could not run: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
