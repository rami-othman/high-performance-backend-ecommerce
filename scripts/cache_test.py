import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django
from django.apps import apps

if not apps.ready:
    django.setup()

from django.contrib.auth import get_user_model

from products.cache_utils import (
    invalidate_daily_sales_report_caches,
    invalidate_product_caches,
)
from products.models import Product
from reports.models import DailySalesBatchRun, DailySalesReport


DEFAULT_BASE_URL = "http://127.0.0.1:8000"
USERNAME = "cache_task6_admin"
PASSWORD = "CacheTask6Password123!"
PRODUCT_NAME = "Cache Task 6 Product"
REPORT_DATE = date(2001, 6, 19)


class CacheTestError(Exception):
    pass


def parse_args():
    parser = argparse.ArgumentParser(description="Task 6 cache proof for product and report endpoints.")
    parser.add_argument(
        "--base-url",
        default=os.getenv("API_BASE_URL", DEFAULT_BASE_URL),
        help="Django API base URL. Defaults to API_BASE_URL or http://127.0.0.1:8000.",
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


def post_json(url, payload, timeout=15):
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
        return response.status, parse_json_body(body)


def get_json(url, headers=None, timeout=15):
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", **(headers or {})},
        method="GET",
    )
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            return {
                "status": response.status,
                "x_cache": response.headers.get("X-Cache"),
                "duration_ms": duration_ms,
                "body": parse_json_body(body),
            }
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        return {
            "status": exc.code,
            "x_cache": exc.headers.get("X-Cache"),
            "duration_ms": duration_ms,
            "body": parse_json_body(body),
        }
    except urllib.error.URLError as exc:
        raise CacheTestError(
            f"Could not connect to the Django API at {url}. "
            "Start the server and check API_BASE_URL or --base-url."
        ) from exc


def setup_demo_data():
    User = get_user_model()
    admin_user, _ = User.objects.update_or_create(
        username=USERNAME,
        defaults={"email": "cache-task6-admin@example.com", "is_staff": True, "is_superuser": True},
    )
    admin_user.set_password(PASSWORD)
    admin_user.save(update_fields=["password", "email", "is_staff", "is_superuser"])

    product, _ = Product.objects.update_or_create(
        name=PRODUCT_NAME,
        defaults={
            "description": "Temporary product used by scripts/cache_test.py.",
            "price": Decimal("17.50"),
            "stock": 25,
        },
    )
    report, _ = DailySalesReport.objects.update_or_create(
        date=REPORT_DATE,
        defaults={
            "total_orders": 3,
            "total_order_items": 3,
            "total_quantity_sold": 6,
            "total_sales": Decimal("105.00"),
            "best_selling_product": product,
        },
    )
    DailySalesBatchRun.objects.filter(report_date=REPORT_DATE).delete()
    batch_run = DailySalesBatchRun.objects.create(
        report_date=REPORT_DATE,
        report=report,
        status=DailySalesBatchRun.Status.SUCCESS,
        chunk_size=2,
        chunks_processed=2,
        total_orders=3,
        total_order_items=3,
        total_quantity_sold=6,
        total_sales=Decimal("105.00"),
        metadata={"chunks": [{"chunk_number": 1}, {"chunk_number": 2}], "algorithm": "cache_task6_demo"},
    )

    invalidate_product_caches([product.id])
    invalidate_daily_sales_report_caches()
    return admin_user, product, batch_run


def obtain_token(base_url):
    try:
        status, payload = post_json(
            f"{base_url}/api/auth/token/",
            {"username": USERNAME, "password": PASSWORD},
        )
    except urllib.error.URLError as exc:
        raise CacheTestError(
            f"Could not connect to the Django API at {base_url}. "
            "Start the server and check API_BASE_URL or --base-url."
        ) from exc
    if status != 200 or "access" not in payload:
        raise CacheTestError(f"JWT login failed. Status: {status}. Response: {payload}")
    return payload["access"]


def call_twice(name, url, headers=None):
    first = get_json(url, headers=headers)
    second = get_json(url, headers=headers)
    return {
        "name": name,
        "url": url,
        "first_request": first,
        "second_request": second,
        "expected_cache_headers": first["x_cache"] == "MISS" and second["x_cache"] == "HIT",
        "duration_delta_ms": round(first["duration_ms"] - second["duration_ms"], 2),
        "second_request_faster_or_equal": second["duration_ms"] <= first["duration_ms"],
    }


def build_summary(results):
    endpoint_count = len(results)
    header_success_count = sum(1 for result in results if result["expected_cache_headers"])
    timing_improved_count = sum(1 for result in results if result["second_request_faster_or_equal"])
    return {
        "endpoint_count": endpoint_count,
        "cache_header_success_count": header_success_count,
        "timing_improved_or_equal_count": timing_improved_count,
        "passed": header_success_count == endpoint_count,
        "timing_note": "Small local timing differences can be noisy; X-Cache proves cache behavior.",
    }


def save_results(result):
    results_dir = BASE_DIR / "results" / "cache"
    results_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    timestamped_path = results_dir / f"cache_task6_{timestamp}.json"
    latest_path = results_dir / "cache_task6_latest.json"

    for path in (timestamped_path, latest_path):
        path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")

    return timestamped_path, latest_path


def print_summary(summary, latest_path):
    print("\nTask 6 - Redis/Django Cache Proof\n")
    print(f"Endpoints checked: {summary['endpoint_count']}")
    print(f"MISS then HIT headers: {summary['cache_header_success_count']}/{summary['endpoint_count']}")
    print(
        "Second request faster or equal: "
        f"{summary['timing_improved_or_equal_count']}/{summary['endpoint_count']}"
    )
    print(f"Result: {'PASSED' if summary['passed'] else 'FAILED'}")
    print(f"\nSaved latest result: {latest_path}")


def main():
    args = parse_args()
    base_url = normalize_base_url(args.base_url)

    try:
        _, product, batch_run = setup_demo_data()
        token = obtain_token(base_url)
        auth_headers = {"Authorization": f"Bearer {token}"}
        endpoint_results = [
            call_twice("products_list", f"{base_url}/api/products/"),
            call_twice("product_detail", f"{base_url}/api/products/{product.id}/"),
            call_twice("daily_sales_reports_list", f"{base_url}/api/reports/daily-sales/", headers=auth_headers),
            call_twice(
                "daily_sales_batch_run_detail",
                f"{base_url}/api/reports/daily-sales/batch-runs/{batch_run.id}/",
                headers=auth_headers,
            ),
        ]
        summary = build_summary(endpoint_results)
        result = {
            "api_base_url": base_url,
            "product_id": product.id,
            "batch_run_id": batch_run.id,
            "summary": summary,
            "endpoints": endpoint_results,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        timestamped_path, latest_path = save_results(result)
        print_summary(summary, latest_path)
        print(f"Saved timestamped result: {timestamped_path}")
        return 0 if summary["passed"] else 1
    except CacheTestError as exc:
        print(f"\nTask 6 cache proof could not run: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
