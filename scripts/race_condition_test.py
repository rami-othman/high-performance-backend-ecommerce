import argparse
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
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
from django.db import transaction
from django.db.models import Sum

from cart.models import Cart, CartItem
from orders.models import Order, OrderItem
from payments.models import Payment
from performance.capacity_limiter import CheckoutCapacityUnavailable, reset_checkout_capacity_metrics
from products.models import Product


DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_PRODUCT_NAME = "Race Condition Test Product"
RACE_CONDITION_TEST_CAPACITY_LIMIT_HEADER = "X-Race-Condition-Test-Capacity-Limit"
RACE_USERNAME_PREFIX = "race_user_"
RACE_PASSWORD = "RaceTestPassword123!"


class RaceTestError(Exception):
    pass


def parse_args():
    parser = argparse.ArgumentParser(description="Task 1 race condition proof for checkout stock locking.")
    parser.add_argument(
        "--base-url",
        default=os.getenv("API_BASE_URL", DEFAULT_BASE_URL),
        help="Django API base URL. Defaults to API_BASE_URL or http://127.0.0.1:8000.",
    )
    parser.add_argument("--users", type=int, default=20, help="Number of concurrent users.")
    parser.add_argument("--stock", type=int, default=5, help="Initial stock for the test product.")
    parser.add_argument("--quantity", type=int, default=1, help="Quantity each user tries to buy.")
    parser.add_argument(
        "--capacity-limit",
        type=int,
        default=None,
        help=(
            "DEBUG-only checkout capacity limit override for proof isolation. "
            "Defaults to max(50, --users)."
        ),
    )
    parser.add_argument(
        "--product-name",
        default=DEFAULT_PRODUCT_NAME,
        help="Name of the test product to create or reset.",
    )
    return parser.parse_args()


def normalize_base_url(base_url):
    return base_url.rstrip("/")


def post_json(url, payload, headers=None, timeout=15):
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
        raise RaceTestError(
            f"Could not connect to the Django API at {url}. "
            "Start the server and check API_BASE_URL or --base-url."
        ) from exc


def get_status(url, timeout=5):
    request = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status
    except urllib.error.URLError as exc:
        raise RaceTestError(
            f"Could not connect to the Django API at {url}. "
            "Start the server and check API_BASE_URL or --base-url."
        ) from exc


def parse_json_body(body):
    if not body:
        return {}
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return {"raw_body": body}


def cleanup_previous_test_data(product_name):
    User = get_user_model()
    User.objects.filter(username__startswith=RACE_USERNAME_PREFIX).delete()

    product = Product.objects.filter(name=product_name).order_by("id").first()
    if product is not None:
        duplicate_products = Product.objects.filter(name=product_name).exclude(id=product.id)
        for duplicate in duplicate_products:
            if not OrderItem.objects.filter(product=duplicate).exists():
                duplicate.delete()
    return product


def setup_test_data(user_count, initial_stock, quantity, product_name):
    if user_count < 1:
        raise RaceTestError("--users must be at least 1.")
    if initial_stock < 0:
        raise RaceTestError("--stock must be 0 or greater.")
    if quantity < 1:
        raise RaceTestError("--quantity must be at least 1.")

    try:
        with transaction.atomic():
            product = cleanup_previous_test_data(product_name)
            if product is None:
                product = Product.objects.create(
                    name=product_name,
                    description="Temporary product used by scripts/race_condition_test.py.",
                    price=Decimal("10.00"),
                    stock=initial_stock,
                )
            else:
                product.description = "Temporary product used by scripts/race_condition_test.py."
                product.price = Decimal("10.00")
                product.stock = initial_stock
                if hasattr(product, "version"):
                    product.version += 1
                    product.save(update_fields=["description", "price", "stock", "version", "updated_at"])
                else:
                    product.save(update_fields=["description", "price", "stock", "updated_at"])

            users = []
            User = get_user_model()
            for index in range(1, user_count + 1):
                username = f"{RACE_USERNAME_PREFIX}{index:03d}"
                user = User.objects.create_user(username=username, password=RACE_PASSWORD)
                cart = Cart.objects.create(user=user)
                CartItem.objects.create(cart=cart, product=product, quantity=quantity)
                users.append(user)

            return product, users
    except Exception as exc:
        raise RaceTestError(f"Database setup failed: {exc}") from exc


def obtain_token(base_url, username):
    status_code, payload, _ = post_json(
        f"{base_url}/api/auth/token/",
        {"username": username, "password": RACE_PASSWORD},
        timeout=15,
    )
    if status_code != 200 or "access" not in payload:
        raise RaceTestError(
            "JWT login failed. Check that the Django API is running and that "
            f"API_BASE_URL/--base-url points to the right server. User: {username}. "
            f"Status: {status_code}. Response: {payload}"
        )
    return payload["access"]


def checkout_user(base_url, username, token, barrier, capacity_limit):
    try:
        barrier.wait(timeout=30)
        status_code, payload, duration_ms = post_json(
            f"{base_url}/api/orders/checkout/",
            {},
            headers={
                "Authorization": f"Bearer {token}",
                RACE_CONDITION_TEST_CAPACITY_LIMIT_HEADER: str(capacity_limit),
            },
            timeout=30,
        )
        return {
            "username": username,
            "status_code": status_code,
            "response": payload,
            "duration_ms": duration_ms,
            "success": 200 <= status_code < 300,
            "failure_reason": classify_failure(status_code, payload),
        }
    except Exception as exc:
        return {
            "username": username,
            "status_code": None,
            "response": {"error": str(exc)},
            "duration_ms": None,
            "success": False,
            "failure_reason": "request_exception",
        }


def run_concurrent_checkouts(base_url, users, capacity_limit):
    tokens = {user.username: obtain_token(base_url, user.username) for user in users}
    barrier = threading.Barrier(len(users))
    results = []

    with ThreadPoolExecutor(max_workers=len(users)) as executor:
        futures = [
            executor.submit(
                checkout_user,
                base_url,
                user.username,
                tokens[user.username],
                barrier,
                capacity_limit,
            )
            for user in users
        ]
        for future in as_completed(futures):
            results.append(future.result())

    return sorted(results, key=lambda item: item["username"])


def classify_failure(status_code, payload):
    if status_code is not None and 200 <= status_code < 300:
        return ""

    code = payload.get("code") if isinstance(payload, dict) else None
    if code:
        return str(code)

    detail = payload.get("detail", "") if isinstance(payload, dict) else ""
    if "not enough stock" in str(detail).lower():
        return "insufficient_stock"

    if status_code is None:
        return "request_exception"
    if status_code >= 500:
        return "server_error"
    return f"http_{status_code}"


def build_failure_metrics(checkout_results):
    status_code_counts = Counter(
        str(result["status_code"]) if result.get("status_code") is not None else "no_response"
        for result in checkout_results
    )
    failure_reasons = Counter(
        result.get("failure_reason") or classify_failure(result.get("status_code"), result.get("response", {}))
        for result in checkout_results
        if not result.get("success")
    )

    return {
        "status_code_counts": dict(sorted(status_code_counts.items())),
        "error_code_counts": dict(sorted(failure_reasons.items())),
        "insufficient_stock_count": failure_reasons.get("insufficient_stock", 0),
        "capacity_rejected_count": failure_reasons.get("checkout_capacity_exceeded", 0),
        "server_error_count": sum(
            1
            for result in checkout_results
            if result.get("status_code") is None or result.get("status_code", 0) >= 500
        ),
    }


def verify_database_state(product, users):
    product.refresh_from_db()
    user_ids = [user.id for user in users]
    successful_orders = Order.objects.filter(user_id__in=user_ids, status=Order.Status.PAID)
    successful_order_ids = list(successful_orders.values_list("id", flat=True))
    total_sold_quantity = (
        OrderItem.objects.filter(order_id__in=successful_order_ids, product=product)
        .aggregate(total=Sum("quantity"))
        .get("total")
        or 0
    )
    payment_count = Payment.objects.filter(
        order_id__in=successful_order_ids,
        status=Payment.Status.COMPLETED,
    ).count()
    return {
        "final_stock": product.stock,
        "successful_order_count": successful_orders.count(),
        "total_sold_quantity": total_sold_quantity,
        "payment_count": payment_count,
    }


def build_summary(
    initial_stock,
    user_count,
    quantity,
    success_count,
    failure_count,
    final_stock,
    successful_order_count,
    total_sold_quantity,
    payment_count,
    failure_metrics,
):
    expected_success_count = initial_stock
    expected_failure_count = user_count - initial_stock
    negative_stock = final_stock < 0
    overselling = total_sold_quantity > initial_stock
    insufficient_stock_count = failure_metrics["insufficient_stock_count"]
    capacity_rejected_count = failure_metrics["capacity_rejected_count"]
    server_error_count = failure_metrics["server_error_count"]
    passed = (
        success_count == initial_stock
        and failure_count == expected_failure_count
        and insufficient_stock_count == expected_failure_count
        and capacity_rejected_count == 0
        and server_error_count == 0
        and final_stock == 0
        and total_sold_quantity == initial_stock
        and final_stock == initial_stock - total_sold_quantity
        and not negative_stock
        and not overselling
        and successful_order_count == success_count
        and total_sold_quantity == success_count * quantity
        and payment_count == success_count
    )

    return {
        "initial_stock": initial_stock,
        "concurrent_users": user_count,
        "quantity_per_user": quantity,
        "expected_successful_checkouts": expected_success_count,
        "expected_failed_checkouts": expected_failure_count,
        "actual_successful_checkouts": success_count,
        "successful_checkouts": success_count,
        "failed_checkouts": failure_count,
        "status_code_counts": failure_metrics["status_code_counts"],
        "error_code_counts": failure_metrics["error_code_counts"],
        "insufficient_stock_count": insufficient_stock_count,
        "capacity_rejected_count": capacity_rejected_count,
        "server_errors": server_error_count,
        "final_stock": final_stock,
        "successful_order_count": successful_order_count,
        "total_sold_quantity": total_sold_quantity,
        "payment_count": payment_count,
        "negative_stock": negative_stock,
        "overselling": overselling,
        "passed": passed,
    }


def save_results(result):
    results_dir = BASE_DIR / "results"
    results_dir.mkdir(exist_ok=True)
    (results_dir / "race_condition").mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    timestamped_path = results_dir / "race_condition" / f"race_condition_task1_{timestamp}.json"
    latest_path = results_dir / "race_condition" / "race_condition_task1_latest.json"

    for path in (timestamped_path, latest_path):
        path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")

    return timestamped_path, latest_path


def print_summary(summary):
    print("\nTask 1 - Race Condition Proof\n")
    print(f"Initial stock: {summary['initial_stock']}")
    print(f"Concurrent users: {summary['concurrent_users']}")
    print(f"Quantity per user: {summary['quantity_per_user']}\n")
    print(f"Successful checkouts: {summary['successful_checkouts']}")
    print(f"Failed checkouts: {summary['failed_checkouts']}")
    print(f"Insufficient stock failures: {summary['insufficient_stock_count']}")
    print(f"Capacity rejections: {summary['capacity_rejected_count']}")
    print(f"Server errors: {summary['server_errors']}")
    print(f"Final stock: {summary['final_stock']}")
    print(f"Total sold quantity: {summary['total_sold_quantity']}")
    print(f"Negative stock: {'Yes' if summary['negative_stock'] else 'No'}")
    print(f"Overselling: {'Yes' if summary['overselling'] else 'No'}\n")
    print(f"Result: {'PASSED' if summary['passed'] else 'FAILED'}")


def main():
    args = parse_args()
    base_url = normalize_base_url(args.base_url)
    capacity_limit = args.capacity_limit if args.capacity_limit is not None else max(50, args.users)

    try:
        get_status(f"{base_url}/api/health/")
        reset_checkout_capacity_metrics()
        product, users = setup_test_data(args.users, args.stock, args.quantity, args.product_name)
        checkout_results = run_concurrent_checkouts(base_url, users, capacity_limit)
        success_count = sum(1 for result in checkout_results if result["success"])
        failure_count = len(checkout_results) - success_count
        failure_metrics = build_failure_metrics(checkout_results)
        db_state = verify_database_state(product, users)
        summary = build_summary(
            initial_stock=args.stock,
            user_count=args.users,
            quantity=args.quantity,
            success_count=success_count,
            failure_count=failure_count,
            final_stock=db_state["final_stock"],
            successful_order_count=db_state["successful_order_count"],
            total_sold_quantity=db_state["total_sold_quantity"],
            payment_count=db_state["payment_count"],
            failure_metrics=failure_metrics,
        )
        result = {
            "api_base_url": base_url,
            "product_id": product.id,
            "product_name": product.name,
            "capacity_limit_override_requested": capacity_limit,
            "summary": summary,
            "database_state": db_state,
            "checkout_results": checkout_results,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        timestamped_path, latest_path = save_results(result)
        print_summary(summary)
        print(f"\nSaved latest result: {latest_path}")
        print(f"Saved timestamped result: {timestamped_path}")
        return 0 if summary["passed"] else 1
    except RaceTestError as exc:
        print(f"\nTask 1 race condition proof could not run: {exc}", file=sys.stderr)
        return 2
    except CheckoutCapacityUnavailable as exc:
        print(f"\nTask 1 race condition proof could not reset capacity metrics: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
