import argparse
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
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

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Sum

from cart.models import Cart, CartItem
from orders.models import Order, OrderItem
from payments.models import Payment
from performance.capacity_limiter import (
    CheckoutCapacityUnavailable,
    get_checkout_capacity_metrics,
    reset_checkout_capacity_metrics,
)
from products.models import Product


DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_PRODUCT_NAME = "Resource Capacity Test Product"
CAPACITY_USERNAME_PREFIX = "capacity_user_"
CAPACITY_PASSWORD = "CapacityTestPassword123!"


class CapacityTestError(Exception):
    pass


def parse_args():
    parser = argparse.ArgumentParser(description="Task 2 resource capacity proof for checkout.")
    parser.add_argument(
        "--base-url",
        default=os.getenv("API_BASE_URL", DEFAULT_BASE_URL),
        help="Django API base URL. Defaults to API_BASE_URL or http://127.0.0.1:8000.",
    )
    parser.add_argument("--users", type=int, default=20, help="Number of concurrent users.")
    parser.add_argument("--stock", type=int, default=100, help="Initial stock for the test product.")
    parser.add_argument("--quantity", type=int, default=1, help="Quantity each user tries to buy.")
    parser.add_argument(
        "--expected-limit",
        type=int,
        default=getattr(settings, "CHECKOUT_MAX_CONCURRENT_REQUESTS", 5),
        help="Expected checkout concurrency limit.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Debug-only X-Capacity-Test-Delay header value, capped by the server at 2 seconds.",
    )
    parser.add_argument(
        "--product-name",
        default=DEFAULT_PRODUCT_NAME,
        help="Name of the test product to create or reset.",
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
        raise CapacityTestError(
            f"Could not connect to the Django API at {url}. "
            "Start the server and check API_BASE_URL or --base-url."
        ) from exc


def get_status(url, timeout=5):
    request = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status
    except urllib.error.URLError as exc:
        raise CapacityTestError(
            f"Could not connect to the Django API at {url}. "
            "Start the server and check API_BASE_URL or --base-url."
        ) from exc


def cleanup_previous_test_data(product_name):
    User = get_user_model()
    User.objects.filter(username__startswith=CAPACITY_USERNAME_PREFIX).delete()

    product = Product.objects.filter(name=product_name).order_by("id").first()
    if product is not None:
        duplicate_products = Product.objects.filter(name=product_name).exclude(pk=product.pk)
        for duplicate in duplicate_products:
            if not OrderItem.objects.filter(product=duplicate).exists():
                duplicate.delete()
    return product


def setup_test_data(user_count, initial_stock, quantity, product_name):
    if user_count < 1:
        raise CapacityTestError("--users must be at least 1.")
    if initial_stock < 0:
        raise CapacityTestError("--stock must be 0 or greater.")
    if quantity < 1:
        raise CapacityTestError("--quantity must be at least 1.")

    try:
        with transaction.atomic():
            product = cleanup_previous_test_data(product_name)
            if product is None:
                product = Product.objects.create(
                    name=product_name,
                    description="Temporary product used by scripts/resource_capacity_test.py.",
                    price=Decimal("10.00"),
                    stock=initial_stock,
                )
            else:
                product.description = "Temporary product used by scripts/resource_capacity_test.py."
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
                username = f"{CAPACITY_USERNAME_PREFIX}{index:03d}"
                user = User.objects.create_user(username=username, password=CAPACITY_PASSWORD)
                cart = Cart.objects.create(user=user)
                CartItem.objects.create(cart=cart, product=product, quantity=quantity)
                users.append(user)

            return product, users
    except Exception as exc:
        raise CapacityTestError(f"Database setup failed: {exc}") from exc


def obtain_token(base_url, username):
    status_code, payload, _ = post_json(
        f"{base_url}/api/auth/token/",
        {"username": username, "password": CAPACITY_PASSWORD},
        timeout=15,
    )
    if status_code != 200 or "access" not in payload:
        raise CapacityTestError(
            "JWT login failed. Check that the Django API is running and that "
            f"API_BASE_URL/--base-url points to the right server. User: {username}. "
            f"Status: {status_code}. Response: {payload}"
        )
    return payload["access"]


def checkout_user(base_url, username, token, barrier, delay):
    try:
        barrier.wait(timeout=30)
        status_code, payload, duration_ms = post_json(
            f"{base_url}/api/orders/checkout/",
            {},
            headers={
                "Authorization": f"Bearer {token}",
                "X-Capacity-Test-Delay": str(delay),
            },
            timeout=40,
        )
        return {
            "username": username,
            "status_code": status_code,
            "response": payload,
            "duration_ms": duration_ms,
            "success": 200 <= status_code < 300,
            "capacity_rejected": status_code == 429 and payload.get("code") == "checkout_capacity_exceeded",
            "server_error": status_code is not None and status_code >= 500,
        }
    except Exception as exc:
        return {
            "username": username,
            "status_code": None,
            "response": {"error": str(exc)},
            "duration_ms": None,
            "success": False,
            "capacity_rejected": False,
            "server_error": True,
        }


def run_concurrent_checkouts(base_url, users, delay):
    tokens = {user.username: obtain_token(base_url, user.username) for user in users}
    barrier = threading.Barrier(len(users))
    results = []

    with ThreadPoolExecutor(max_workers=len(users)) as executor:
        futures = [
            executor.submit(checkout_user, base_url, user.username, tokens[user.username], barrier, delay)
            for user in users
        ]
        for future in as_completed(futures):
            results.append(future.result())

    return sorted(results, key=lambda item: item["username"])


def verify_database_state(product, users):
    product.refresh_from_db()
    user_ids = [user.pk for user in users]
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
    configured_limit,
    user_count,
    initial_stock,
    quantity,
    success_count,
    capacity_rejected_count,
    other_failed_count,
    server_error_count,
    final_stock,
    total_sold_quantity,
    max_observed_active_checkouts,
    delay_seconds=1.0,
    successful_order_count=None,
    payment_count=None,
):
    successful_order_count = success_count if successful_order_count is None else successful_order_count
    payment_count = success_count if payment_count is None else payment_count
    limit_respected = max_observed_active_checkouts <= configured_limit
    overlap_observed = max_observed_active_checkouts > 1
    capacity_rejection_required = user_count > configured_limit and delay_seconds > 0
    capacity_rejection_present = capacity_rejected_count > 0 or not capacity_rejection_required
    passed = (
        server_error_count == 0
        and final_stock >= 0
        and total_sold_quantity <= initial_stock
        and limit_respected
        and overlap_observed
        and capacity_rejection_present
        and successful_order_count <= success_count
        and total_sold_quantity == successful_order_count * quantity
        and payment_count == successful_order_count
    )

    return {
        "configured_checkout_limit": configured_limit,
        "concurrent_users": user_count,
        "initial_stock": initial_stock,
        "quantity_per_user": quantity,
        "successful_checkouts": success_count,
        "capacity_rejected_count": capacity_rejected_count,
        "other_failed_requests": other_failed_count,
        "server_errors": server_error_count,
        "final_stock": final_stock,
        "total_sold_quantity": total_sold_quantity,
        "successful_order_count": successful_order_count,
        "payment_count": payment_count,
        "max_observed_active_checkouts": max_observed_active_checkouts,
        "limit_respected": limit_respected,
        "overlap_observed": overlap_observed,
        "passed": passed,
    }


def save_results(result):
    results_dir = BASE_DIR / "results"
    results_dir.mkdir(exist_ok=True)
    (results_dir / "resource_capacity").mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    timestamped_path = results_dir / "resource_capacity" / f"resource_capacity_task2_{timestamp}.json"
    latest_path = results_dir / "resource_capacity" / "resource_capacity_task2_latest.json"

    for path in (timestamped_path, latest_path):
        path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")

    return timestamped_path, latest_path


def print_summary(summary):
    print("\nTask 2 - Resource Management & Capacity Control Proof\n")
    print(f"Configured checkout limit: {summary['configured_checkout_limit']}")
    print(f"Concurrent users: {summary['concurrent_users']}")
    print(f"Initial stock: {summary['initial_stock']}")
    print(f"Quantity per user: {summary['quantity_per_user']}\n")
    print(f"Successful checkouts: {summary['successful_checkouts']}")
    print(f"Rejected by capacity limiter: {summary['capacity_rejected_count']}")
    print(f"Other failed requests: {summary['other_failed_requests']}")
    print(f"Server errors: {summary['server_errors']}")
    print(f"Final stock: {summary['final_stock']}")
    print(f"Max observed active checkouts: {summary['max_observed_active_checkouts']}")
    print(f"Limit respected: {'Yes' if summary['limit_respected'] else 'No'}")
    print(f"Concurrent overlap observed: {'Yes' if summary['overlap_observed'] else 'No'}")
    print(f"\nResult: {'PASSED' if summary['passed'] else 'FAILED'}")


def main():
    args = parse_args()
    base_url = normalize_base_url(args.base_url)

    try:
        get_status(f"{base_url}/api/health/")
        product, users = setup_test_data(args.users, args.stock, args.quantity, args.product_name)
        reset_checkout_capacity_metrics()
        checkout_results = run_concurrent_checkouts(base_url, users, args.delay)
        metrics = get_checkout_capacity_metrics()
        db_state = verify_database_state(product, users)

        success_count = sum(1 for result in checkout_results if result["success"])
        capacity_rejected_count = sum(1 for result in checkout_results if result["capacity_rejected"])
        server_error_count = sum(1 for result in checkout_results if result["server_error"])
        other_failed_count = len(checkout_results) - success_count - capacity_rejected_count - server_error_count

        summary = build_summary(
            configured_limit=args.expected_limit,
            user_count=args.users,
            initial_stock=args.stock,
            quantity=args.quantity,
            success_count=success_count,
            capacity_rejected_count=capacity_rejected_count,
            other_failed_count=other_failed_count,
            server_error_count=server_error_count,
            final_stock=db_state["final_stock"],
            total_sold_quantity=db_state["total_sold_quantity"],
            max_observed_active_checkouts=metrics["max_observed_active_checkouts"],
            delay_seconds=args.delay,
            successful_order_count=db_state["successful_order_count"],
            payment_count=db_state["payment_count"],
        )
        result = {
            "api_base_url": base_url,
            "product_id": product.pk,
            "product_name": product.name,
            "capacity_metrics": metrics,
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
    except CheckoutCapacityUnavailable as exc:
        print(f"\nTask 2 proof could not run because Redis is unavailable: {exc}", file=sys.stderr)
        return 2
    except CapacityTestError as exc:
        print(f"\nTask 2 proof could not run: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
