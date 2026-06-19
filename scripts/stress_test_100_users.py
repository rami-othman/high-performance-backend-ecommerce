import argparse
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
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
from django.db import connections, transaction
from django.db.models import Sum
from rest_framework_simplejwt.tokens import RefreshToken

from cart.models import Cart
from orders.models import Order, OrderItem
from payments.models import Payment
from products.cache_utils import invalidate_product_caches
from products.models import Product
from reports.models import DailySalesBatchRun


DEFAULT_BASE_URL = "http://127.0.0.1:8000"
USERNAME_PREFIX = "stress_task9_user_"
PRODUCT_PREFIX = "Stress Task 9 Product"
PASSWORD = "StressTask9Password123!"
CAPACITY_LIMIT_HEADER = "X-Race-Condition-Test-Capacity-Limit"
SUCCESS_STATUS_CODES = {200, 201, 202, 204}


class StressTestError(Exception):
    pass


def parse_args():
    parser = argparse.ArgumentParser(description="Task 9 stress test with 100 concurrent e-commerce users.")
    parser.add_argument(
        "--base-url",
        default=os.getenv("API_BASE_URL", DEFAULT_BASE_URL),
        help="Django API base URL. Defaults to API_BASE_URL or http://127.0.0.1:8000.",
    )
    parser.add_argument("--users", type=int, default=100, help="Number of concurrent simulated users.")
    parser.add_argument("--products", type=int, default=10, help="Number of isolated stress products to create.")
    parser.add_argument("--quantity", type=int, default=1, help="Quantity each user checks out.")
    parser.add_argument(
        "--stock-buffer",
        type=int,
        default=10,
        help="Extra stock per product above the expected per-product demand.",
    )
    parser.add_argument(
        "--checkout-capacity-limit",
        type=int,
        default=None,
        help=(
            "DEBUG-only checkout capacity override sent with checkout requests. "
            "Defaults to max(150, --users). Production ignores this header."
        ),
    )
    parser.add_argument("--timeout", type=float, default=60.0, help="HTTP timeout per request in seconds.")
    parser.add_argument(
        "--warm-cache",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Warm product list/detail caches before the concurrent phase.",
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
        return {"raw_body": body[:500]}


def timed_operation(operation, func):
    start = time.perf_counter()
    try:
        status_code, payload, headers = func()
        error = ""
    except Exception as exc:
        status_code = None
        payload = {"error": str(exc)}
        headers = {}
        error = str(exc)

    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    return {
        "operation": operation,
        "status_code": status_code,
        "duration_ms": duration_ms,
        "response": payload,
        "headers": headers,
        "error": error,
    }


def request_json(method, url, payload=None, headers=None, timeout=30):
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Accept": "application/json",
            "Connection": "close",
            **({"Content-Type": "application/json"} if payload is not None else {}),
            **(headers or {}),
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return response.status, parse_json_body(body), dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return exc.code, parse_json_body(body), dict(exc.headers.items())
    except urllib.error.URLError as exc:
        raise StressTestError(str(exc)) from exc


def get_json(base_url, path, token=None, timeout=30, extra_headers=None):
    headers = dict(extra_headers or {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return request_json("GET", f"{base_url}{path}", headers=headers, timeout=timeout)


def post_json(base_url, path, payload, token=None, timeout=30, extra_headers=None):
    headers = dict(extra_headers or {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return request_json("POST", f"{base_url}{path}", payload=payload, headers=headers, timeout=timeout)


def patch_json(base_url, path, payload, token=None, timeout=30):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return request_json("PATCH", f"{base_url}{path}", payload=payload, headers=headers, timeout=timeout)


def wait_for_health(base_url, timeout_seconds):
    deadline = time.monotonic() + timeout_seconds
    last_result = None
    while time.monotonic() < deadline:
        last_result = timed_operation(
            "health",
            lambda: get_json(base_url, "/api/health/", timeout=5),
        )
        if last_result["status_code"] == 200:
            return last_result
        time.sleep(1)

    raise StressTestError(f"API did not become healthy at {base_url}/api/health/. Last result: {last_result}")


def cleanup_previous_data():
    User = get_user_model()
    User.objects.filter(username__startswith=USERNAME_PREFIX).delete()
    Product.objects.filter(name__startswith=PRODUCT_PREFIX).delete()


def create_stress_products(user_count, product_count, quantity, stock_buffer):
    if user_count < 1:
        raise StressTestError("--users must be at least 1.")
    if product_count < 1:
        raise StressTestError("--products must be at least 1.")
    if quantity < 1:
        raise StressTestError("--quantity must be at least 1.")
    if stock_buffer < 0:
        raise StressTestError("--stock-buffer must be at least 0.")

    stock_per_product = math.ceil(user_count / product_count) * quantity + stock_buffer
    products = []
    with transaction.atomic():
        cleanup_previous_data()
        for index in range(1, product_count + 1):
            product = Product.objects.create(
                name=f"{PRODUCT_PREFIX} {index:02d}",
                description="Temporary product used by scripts/stress_test_100_users.py.",
                price=Decimal("19.99"),
                stock=stock_per_product,
            )
            products.append(product)

    invalidate_product_caches([product.id for product in products])
    return products


def create_stress_user(user_number):
    start = time.perf_counter()
    User = get_user_model()
    username = f"{USERNAME_PREFIX}{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{user_number:03d}"
    user = User.objects.create_user(
        username=username,
        email=f"{username}@example.com",
        password=PASSWORD,
    )
    Cart.objects.get_or_create(user=user)
    refresh = RefreshToken.for_user(user)
    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    return {
        "user_number": user_number,
        "user_id": user.id,
        "username": user.username,
        "access": str(refresh.access_token),
        "setup_record": {
            "operation": "create_test_user_and_issue_jwt",
            "status_code": 200,
            "duration_ms": duration_ms,
            "response": {"user_id": user.id, "username": user.username},
            "headers": {},
            "error": "",
        },
    }


def create_stress_users(user_count):
    users = []
    for user_number in range(1, user_count + 1):
        users.append(create_stress_user(user_number))
    return users


def create_admin_stress_user():
    start = time.perf_counter()
    User = get_user_model()
    username = f"{USERNAME_PREFIX}admin_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
    user = User.objects.create_user(
        username=username,
        email=f"{username}@example.com",
        password=PASSWORD,
        is_staff=True,
        is_superuser=True,
    )
    refresh = RefreshToken.for_user(user)
    duration_ms = round((time.perf_counter() - start) * 1000, 2)
    return {
        "user_number": "admin",
        "user_id": user.id,
        "username": user.username,
        "access": str(refresh.access_token),
        "setup_record": {
            "operation": "create_admin_report_user_and_issue_jwt",
            "status_code": 200,
            "duration_ms": duration_ms,
            "response": {"user_id": user.id, "username": user.username},
            "headers": {},
            "error": "",
        },
    }


def warm_product_caches(base_url, products, timeout):
    records = [
        timed_operation("warm_product_list", lambda: get_json(base_url, "/api/products/", timeout=timeout))
    ]
    for product in products:
        records.append(
            timed_operation(
                "warm_product_detail",
                lambda product_id=product.id: get_json(base_url, f"/api/products/{product_id}/", timeout=timeout),
            )
        )
    return records


def operation_succeeded(record, allowed_status_codes=None):
    allowed_status_codes = allowed_status_codes or SUCCESS_STATUS_CODES
    return record["status_code"] in allowed_status_codes and not record.get("error")


def run_user_flow(base_url, user_context, product_id, quantity, checkout_capacity_limit, timeout):
    records = []
    checkout_success = False
    order_history_seen = False
    user_number = user_context["user_number"]
    user_id = user_context["user_id"]
    username = user_context["username"]
    token = user_context["access"]

    try:
        flow = [
            (
                "get_product_list",
                lambda: get_json(base_url, "/api/products/", token=token, timeout=timeout),
                SUCCESS_STATUS_CODES,
            ),
            (
                "get_product_detail",
                lambda: get_json(base_url, f"/api/products/{product_id}/", token=token, timeout=timeout),
                SUCCESS_STATUS_CODES,
            ),
            (
                "add_product_to_cart",
                lambda: post_json(
                    base_url,
                    "/api/cart/items/",
                    {"product": product_id, "quantity": quantity},
                    token=token,
                    timeout=timeout,
                ),
                {201},
            ),
        ]

        cart_item_id = None
        for operation, func, allowed_statuses in flow:
            record = timed_operation(operation, func)
            records.append(record)
            if not operation_succeeded(record, allowed_statuses):
                return build_user_result(user_number, user_id, username, records, checkout_success, order_history_seen)
            if operation == "add_product_to_cart":
                cart_item_id = record["response"].get("id")

        if cart_item_id:
            records.append(
                timed_operation(
                    "update_cart_item_quantity",
                    lambda: patch_json(
                        base_url,
                        f"/api/cart/items/{cart_item_id}/",
                        {"quantity": quantity},
                        token=token,
                        timeout=timeout,
                    ),
                )
            )
            if not operation_succeeded(records[-1]):
                return build_user_result(user_number, user_id, username, records, checkout_success, order_history_seen)

        checkout_headers = {CAPACITY_LIMIT_HEADER: str(checkout_capacity_limit)}
        checkout_record = timed_operation(
            "checkout",
            lambda: post_json(
                base_url,
                "/api/orders/checkout/",
                {},
                token=token,
                timeout=timeout,
                extra_headers=checkout_headers,
            ),
        )
        records.append(checkout_record)
        checkout_success = checkout_record["status_code"] == 201
        if not checkout_success:
            return build_user_result(user_number, user_id, username, records, checkout_success, order_history_seen)

        orders_record = timed_operation(
            "get_order_history",
            lambda: get_json(base_url, "/api/orders/", token=token, timeout=timeout),
        )
        records.append(orders_record)
        order_history_seen = operation_succeeded(orders_record) and bool(orders_record["response"])

        records.append(
            timed_operation(
                "get_cached_product_detail_again",
                lambda: get_json(base_url, f"/api/products/{product_id}/", token=token, timeout=timeout),
            )
        )

        records.append(
            timed_operation(
                "get_performance_capacity",
                lambda: get_json(base_url, "/api/performance/capacity/", token=token, timeout=timeout),
            )
        )

        records.append(
            timed_operation(
                "get_daily_sales_report_as_regular_user",
                lambda: get_json(base_url, "/api/reports/daily-sales/", token=token, timeout=timeout),
            )
        )

        return build_user_result(user_number, user_id, username, records, checkout_success, order_history_seen)
    except Exception as exc:
        records.append(
            {
                "operation": "user_flow_exception",
                "status_code": None,
                "duration_ms": 0.0,
                "response": {},
                "headers": {},
                "error": str(exc),
            }
        )
        return build_user_result(user_number, user_id, username, records, checkout_success, order_history_seen)
    finally:
        connections.close_all()


def build_user_result(user_number, user_id, username, records, checkout_success, order_history_seen):
    failed_records = [
        record
        for record in records
        if not operation_succeeded(record, allowed_status_codes=allowed_statuses_for_operation(record["operation"]))
    ]
    return {
        "user_number": user_number,
        "user_id": user_id,
        "username": username,
        "checkout_success": checkout_success,
        "order_history_seen": order_history_seen,
        "success": checkout_success and order_history_seen and not failed_records,
        "records": records,
        "failed_operations": [
            {
                "operation": record["operation"],
                "status_code": record["status_code"],
                "error": record["error"] or classify_error(record),
            }
            for record in failed_records
        ],
    }


def allowed_statuses_for_operation(operation):
    if operation in {"get_performance_capacity", "get_daily_sales_report_as_regular_user"}:
        return {200, 403}
    if operation in {"create_test_user_and_issue_jwt", "create_admin_report_user_and_issue_jwt"}:
        return {200}
    if operation in {"get_daily_sales_report_as_admin", "get_daily_sales_batch_run_as_admin"}:
        return {200}
    if operation == "add_product_to_cart":
        return {201}
    if operation == "checkout":
        return {201}
    return SUCCESS_STATUS_CODES


def classify_error(record):
    if record["status_code"] is None:
        return record["error"] or "no_response"
    response = record.get("response") or {}
    if isinstance(response, dict):
        return str(response.get("code") or response.get("detail") or response.get("error") or f"http_{record['status_code']}")
    return f"http_{record['status_code']}"


def percentile(values, percentile_value):
    if not values:
        return 0.0
    sorted_values = sorted(values)
    index = max(0, math.ceil((percentile_value / 100) * len(sorted_values)) - 1)
    return round(sorted_values[index], 2)


def calculate_timing_summary(request_records, total_duration_seconds):
    durations = [record["duration_ms"] for record in request_records]
    total_requests = len(request_records)
    status_distribution = Counter(
        str(record["status_code"]) if record["status_code"] is not None else "no_response"
        for record in request_records
    )
    error_count = sum(
        1
        for record in request_records
        if not operation_succeeded(record, allowed_status_codes=allowed_statuses_for_operation(record["operation"]))
    )

    per_operation_records = defaultdict(list)
    for record in request_records:
        per_operation_records[record["operation"]].append(record)

    per_operation = {}
    for operation, records in sorted(per_operation_records.items()):
        operation_durations = [record["duration_ms"] for record in records]
        operation_errors = sum(
            1
            for record in records
            if not operation_succeeded(record, allowed_status_codes=allowed_statuses_for_operation(operation))
        )
        per_operation[operation] = {
            "count": len(records),
            "errors": operation_errors,
            "average_ms": round(sum(operation_durations) / len(operation_durations), 2),
            "min_ms": round(min(operation_durations), 2),
            "max_ms": round(max(operation_durations), 2),
            "p95_ms": percentile(operation_durations, 95),
        }

    return {
        "total_requests": total_requests,
        "average_response_time_ms": round(sum(durations) / total_requests, 2) if durations else 0.0,
        "min_response_time_ms": round(min(durations), 2) if durations else 0.0,
        "max_response_time_ms": round(max(durations), 2) if durations else 0.0,
        "p95_response_time_ms": percentile(durations, 95),
        "requests_per_second": round(total_requests / total_duration_seconds, 2) if total_duration_seconds else 0.0,
        "error_rate": round(error_count / total_requests, 4) if total_requests else 0.0,
        "status_code_distribution": dict(sorted(status_distribution.items())),
        "per_operation": per_operation,
    }


def collect_request_records(user_results):
    return [record for user_result in user_results for record in user_result["records"]]


def collect_failed_requests(user_results):
    failures = []
    for user_result in user_results:
        for failed_operation in user_result["failed_operations"]:
            failures.append(
                {
                    "user_number": user_result["user_number"],
                    "user_id": user_result["user_id"],
                    "username": user_result["username"],
                    **failed_operation,
                }
            )
    return failures


def run_admin_report_operations(base_url, admin_context, timeout):
    records = [
        timed_operation(
            "get_daily_sales_report_as_admin",
            lambda: get_json(base_url, "/api/reports/daily-sales/", token=admin_context["access"], timeout=timeout),
        )
    ]

    batch_run = DailySalesBatchRun.objects.order_by("-id").first()
    if batch_run is not None:
        records.append(
            timed_operation(
                "get_daily_sales_batch_run_as_admin",
                lambda batch_run_id=batch_run.id: get_json(
                    base_url,
                    f"/api/reports/daily-sales/batch-runs/{batch_run_id}/",
                    token=admin_context["access"],
                    timeout=timeout,
                ),
            )
        )

    failed_operations = [
        {
            "operation": record["operation"],
            "status_code": record["status_code"],
            "error": record["error"] or classify_error(record),
        }
        for record in records
        if not operation_succeeded(record, allowed_status_codes=allowed_statuses_for_operation(record["operation"]))
    ]
    return {
        "user_number": admin_context["user_number"],
        "user_id": admin_context["user_id"],
        "username": admin_context["username"],
        "success": not failed_operations,
        "records": records,
        "failed_operations": failed_operations,
    }


def collect_admin_failed_requests(admin_report_result):
    return [
        {
            "user_number": admin_report_result["user_number"],
            "user_id": admin_report_result["user_id"],
            "username": admin_report_result["username"],
            **failed_operation,
        }
        for failed_operation in admin_report_result["failed_operations"]
    ]


def verify_database_state(products, user_results):
    product_ids = [product.id for product in products]
    initial_stock_by_product = {product.id: product._stress_initial_stock for product in products}
    final_stock_by_product = dict(Product.objects.filter(id__in=product_ids).values_list("id", "stock"))
    user_ids = [result["user_id"] for result in user_results if result["user_id"]]
    successful_checkout_count = sum(1 for result in user_results if result["checkout_success"])
    paid_orders = Order.objects.filter(user_id__in=user_ids, status=Order.Status.PAID)
    paid_order_ids = list(paid_orders.values_list("id", flat=True))

    sold_rows = (
        OrderItem.objects.filter(order_id__in=paid_order_ids, product_id__in=product_ids)
        .values("product_id")
        .annotate(total=Sum("quantity"))
    )
    sold_quantity_by_product = {product_id: 0 for product_id in product_ids}
    for row in sold_rows:
        sold_quantity_by_product[row["product_id"]] = row["total"] or 0

    return build_data_integrity_summary(
        initial_stock_by_product=initial_stock_by_product,
        final_stock_by_product=final_stock_by_product,
        sold_quantity_by_product=sold_quantity_by_product,
        successful_checkout_count=successful_checkout_count,
        order_count=paid_orders.count(),
        payment_count=Payment.objects.filter(order_id__in=paid_order_ids, status=Payment.Status.COMPLETED).count(),
    )


def build_data_integrity_summary(
    initial_stock_by_product,
    final_stock_by_product,
    sold_quantity_by_product,
    successful_checkout_count,
    order_count,
    payment_count,
):
    product_checks = {}
    negative_stock = False
    overselling = False
    stock_matches_sales = True

    for product_id, initial_stock in sorted(initial_stock_by_product.items()):
        final_stock = final_stock_by_product.get(product_id, 0)
        sold_quantity = sold_quantity_by_product.get(product_id, 0)
        expected_final_stock = initial_stock - sold_quantity
        product_negative_stock = final_stock < 0
        product_oversold = sold_quantity > initial_stock
        product_stock_matches_sales = final_stock == expected_final_stock
        negative_stock = negative_stock or product_negative_stock
        overselling = overselling or product_oversold
        stock_matches_sales = stock_matches_sales and product_stock_matches_sales
        product_checks[str(product_id)] = {
            "initial_stock": initial_stock,
            "final_stock": final_stock,
            "sold_quantity": sold_quantity,
            "expected_final_stock": expected_final_stock,
            "negative_stock": product_negative_stock,
            "oversold": product_oversold,
            "stock_matches_sales": product_stock_matches_sales,
        }

    orders_match = order_count == successful_checkout_count
    payments_match = payment_count == successful_checkout_count
    passed = (
        not negative_stock
        and not overselling
        and stock_matches_sales
        and orders_match
        and payments_match
    )

    return {
        "passed": passed,
        "negative_stock": negative_stock,
        "overselling": overselling,
        "stock_matches_sales": stock_matches_sales,
        "orders_match_successful_checkouts": orders_match,
        "payments_match_successful_checkouts": payments_match,
        "successful_checkout_count": successful_checkout_count,
        "order_count": order_count,
        "payment_count": payment_count,
        "products": product_checks,
    }


def build_summary(
    total_users,
    user_results,
    request_records,
    failed_requests,
    timing_summary,
    data_integrity,
    report_operations_passed=True,
):
    successful_checkouts = sum(1 for result in user_results if result["checkout_success"])
    failed_checkouts = total_users - successful_checkouts
    successful_users = sum(1 for result in user_results if result["success"])
    failed_users = total_users - successful_users
    server_error_count = sum(
        1
        for record in request_records
        if record["status_code"] is None or record["status_code"] >= 500
    )
    passed = (
        total_users >= 100
        and successful_checkouts == total_users
        and failed_users == 0
        and server_error_count == 0
        and data_integrity["passed"]
        and report_operations_passed
    )

    return {
        "total_users": total_users,
        "total_requests": timing_summary["total_requests"],
        "successful_users": successful_users,
        "failed_users": failed_users,
        "successful_checkouts": successful_checkouts,
        "failed_checkouts": failed_checkouts,
        "server_error_count": server_error_count,
        "failed_request_count": len(failed_requests),
        "report_operations_passed": report_operations_passed,
        "average_response_time_ms": timing_summary["average_response_time_ms"],
        "min_response_time_ms": timing_summary["min_response_time_ms"],
        "max_response_time_ms": timing_summary["max_response_time_ms"],
        "p95_response_time_ms": timing_summary["p95_response_time_ms"],
        "requests_per_second": timing_summary["requests_per_second"],
        "error_rate": timing_summary["error_rate"],
        "status_code_distribution": timing_summary["status_code_distribution"],
        "passed": passed,
        "result": "PASSED" if passed else "FAILED",
    }


def save_json_result(result):
    results_dir = BASE_DIR / "results" / "stress"
    results_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    timestamped_path = results_dir / f"task9_stress_100_users_{timestamp}.json"
    latest_path = results_dir / "task9_stress_100_users_latest.json"

    for path in (timestamped_path, latest_path):
        path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")

    return timestamped_path, latest_path


def save_markdown_summary(result):
    path = BASE_DIR / "results" / "stress" / "task9_stress_100_users_summary.md"
    summary = result["summary"]
    data_integrity = result["data_integrity"]
    timing = result["timing"]
    lines = [
        "# Task 9 Stress Test Summary",
        "",
        f"- Result: **{summary['result']}**",
        f"- Total users: {summary['total_users']}",
        f"- Total requests: {summary['total_requests']}",
        f"- Successful users: {summary['successful_users']}",
        f"- Failed users: {summary['failed_users']}",
        f"- Successful checkouts: {summary['successful_checkouts']}",
        f"- Failed checkouts: {summary['failed_checkouts']}",
        f"- Requests per second: {summary['requests_per_second']}",
        f"- Average response time: {summary['average_response_time_ms']} ms",
        f"- Min response time: {summary['min_response_time_ms']} ms",
        f"- Max response time: {summary['max_response_time_ms']} ms",
        f"- P95 response time: {summary['p95_response_time_ms']} ms",
        f"- Error rate: {summary['error_rate']}",
        f"- Server errors: {summary['server_error_count']}",
        f"- Report operations passed: {summary['report_operations_passed']}",
        "",
        "## Data Integrity",
        "",
        f"- Passed: {data_integrity['passed']}",
        f"- Negative stock: {data_integrity['negative_stock']}",
        f"- Overselling: {data_integrity['overselling']}",
        f"- Stock matches sales: {data_integrity['stock_matches_sales']}",
        f"- Orders match successful checkouts: {data_integrity['orders_match_successful_checkouts']}",
        f"- Payments match successful checkouts: {data_integrity['payments_match_successful_checkouts']}",
        "",
        "## Status Codes",
        "",
    ]
    for status_code, count in summary["status_code_distribution"].items():
        lines.append(f"- `{status_code}`: {count}")

    lines.extend(["", "## Per-Operation Timing", ""])
    for operation, operation_summary in timing["per_operation"].items():
        lines.append(
            f"- `{operation}`: count={operation_summary['count']}, errors={operation_summary['errors']}, "
            f"avg={operation_summary['average_ms']} ms, p95={operation_summary['p95_ms']} ms"
        )

    if result["failed_requests"]:
        lines.extend(["", "## Failed Requests", ""])
        for failure in result["failed_requests"][:50]:
            lines.append(
                f"- user={failure['user_number']} operation=`{failure['operation']}` "
                f"status={failure['status_code']} error={failure['error']}"
            )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def print_summary(result, latest_path, markdown_path):
    summary = result["summary"]
    print("\nTask 9 - 100 User Stress Test\n")
    print(f"Total users: {summary['total_users']}")
    print(f"Total requests: {summary['total_requests']}")
    print(f"Successful users: {summary['successful_users']}")
    print(f"Failed users: {summary['failed_users']}")
    print(f"Successful checkouts: {summary['successful_checkouts']}")
    print(f"Failed checkouts: {summary['failed_checkouts']}")
    print(f"Requests/sec: {summary['requests_per_second']}")
    print(f"P95 response time: {summary['p95_response_time_ms']} ms")
    print(f"Error rate: {summary['error_rate']}")
    print(f"Data integrity passed: {'Yes' if result['data_integrity']['passed'] else 'No'}")
    print(f"Result: {summary['result']}")
    print(f"\nSaved latest JSON: {latest_path}")
    print(f"Saved markdown summary: {markdown_path}")


def main():
    args = parse_args()
    base_url = normalize_base_url(args.base_url)
    checkout_capacity_limit = args.checkout_capacity_limit or max(150, args.users)

    try:
        health_record = wait_for_health(base_url, args.timeout)
        products = create_stress_products(args.users, args.products, args.quantity, args.stock_buffer)
        for product in products:
            product._stress_initial_stock = product.stock
        user_contexts = create_stress_users(args.users)
        admin_context = create_admin_stress_user()
        setup_records = [user_context["setup_record"] for user_context in user_contexts]
        setup_records.append(admin_context["setup_record"])

        warm_records = warm_product_caches(base_url, products, args.timeout) if args.warm_cache else []

        started_at = time.perf_counter()
        user_results = []
        with ThreadPoolExecutor(max_workers=args.users) as executor:
            futures = [
                executor.submit(
                    run_user_flow,
                    base_url,
                    user_context,
                    products[(user_context["user_number"] - 1) % len(products)].id,
                    args.quantity,
                    checkout_capacity_limit,
                    args.timeout,
                )
                for user_context in user_contexts
            ]
            for future in as_completed(futures):
                user_results.append(future.result())

        user_results.sort(key=lambda result: result["user_number"])
        admin_report_result = run_admin_report_operations(base_url, admin_context, args.timeout)
        total_duration_seconds = round(time.perf_counter() - started_at, 4)
        request_records = setup_records + collect_request_records(user_results) + admin_report_result["records"]
        failed_requests = collect_failed_requests(user_results) + collect_admin_failed_requests(admin_report_result)
        timing_summary = calculate_timing_summary(request_records, total_duration_seconds)
        data_integrity = verify_database_state(products, user_results)
        summary = build_summary(
            total_users=args.users,
            user_results=user_results,
            request_records=request_records,
            failed_requests=failed_requests,
            timing_summary=timing_summary,
            data_integrity=data_integrity,
            report_operations_passed=admin_report_result["success"],
        )
        result = {
            "summary": summary,
            "timing": timing_summary,
            "data_integrity": data_integrity,
            "failed_requests": failed_requests,
            "user_results": user_results,
            "admin_report_operations": admin_report_result,
            "health_check": health_record,
            "warm_cache_records": warm_records,
            "configuration": {
                "api_base_url": base_url,
                "users": args.users,
                "products": args.products,
                "quantity": args.quantity,
                "stock_buffer": args.stock_buffer,
                "checkout_capacity_limit_header": checkout_capacity_limit,
                "warm_cache": args.warm_cache,
            },
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        timestamped_path, latest_path = save_json_result(result)
        markdown_path = save_markdown_summary(result)
        print_summary(result, latest_path, markdown_path)
        print(f"Saved timestamped JSON: {timestamped_path}")
        return 0 if summary["passed"] else 1
    except StressTestError as exc:
        print(f"\nTask 9 stress test could not run: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
