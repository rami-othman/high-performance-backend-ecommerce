import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
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
from orders.models import Order, OrderBackgroundTask, OrderItem
from payments.models import Payment
from products.models import Product


DEFAULT_BASE_URL = "http://127.0.0.1:8000"
USERNAME_PREFIX = "acid_task8_user_"
PRODUCT_PREFIX = "ACID Task 8 Product"
PASSWORD = "AcidTask8Password123!"
FAILURE_HEADER = "X-Debug-Fail-Checkout-After-Stock"


class AcidTransactionTestError(Exception):
    pass


def parse_args():
    parser = argparse.ArgumentParser(description="Task 8 ACID transaction proof for checkout.")
    parser.add_argument(
        "--base-url",
        default=os.getenv("API_BASE_URL", DEFAULT_BASE_URL),
        help="Django API base URL. Defaults to API_BASE_URL or http://127.0.0.1:8000.",
    )
    parser.add_argument("--stock", type=int, default=5, help="Initial stock for each proof product.")
    parser.add_argument("--quantity", type=int, default=2, help="Cart quantity for each checkout.")
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


def post_json(url, payload, headers=None, timeout=30):
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
        body = exc.read().decode("utf-8", errors="replace")
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        return exc.code, parse_json_body(body), duration_ms
    except urllib.error.URLError as exc:
        raise AcidTransactionTestError(
            f"Could not connect to the Django API at {url}. "
            "Start the server and check API_BASE_URL or --base-url."
        ) from exc


def get_status(url, timeout=5):
    request = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status
    except urllib.error.URLError as exc:
        raise AcidTransactionTestError(
            f"Could not connect to the Django API at {url}. "
            "Start the server and check API_BASE_URL or --base-url."
        ) from exc


def cleanup_previous_data():
    User = get_user_model()
    User.objects.filter(username__startswith=USERNAME_PREFIX).delete()
    Product.objects.filter(name__startswith=PRODUCT_PREFIX, order_items__isnull=True).delete()


def create_fixture(case_name, initial_stock, quantity):
    if initial_stock < 1:
        raise AcidTransactionTestError("--stock must be at least 1.")
    if quantity < 1:
        raise AcidTransactionTestError("--quantity must be at least 1.")
    if quantity > initial_stock:
        raise AcidTransactionTestError("--quantity must be less than or equal to --stock.")

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    username = f"{USERNAME_PREFIX}{case_name}_{timestamp}"
    product_name = f"{PRODUCT_PREFIX} {case_name} {timestamp}"

    with transaction.atomic():
        User = get_user_model()
        user = User.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password=PASSWORD,
        )
        product = Product.objects.create(
            name=product_name,
            description="Temporary product used by scripts/acid_transaction_test.py.",
            price=Decimal("13.00"),
            stock=initial_stock,
        )
        cart = Cart.objects.create(user=user)
        CartItem.objects.create(cart=cart, product=product, quantity=quantity)

    return user, product


def obtain_token(base_url, username):
    status_code, payload, _ = post_json(
        f"{base_url}/api/auth/token/",
        {"username": username, "password": PASSWORD},
        timeout=15,
    )
    if status_code != 200 or "access" not in payload:
        raise AcidTransactionTestError(
            "JWT login failed. Check that the Django API is running and that "
            f"API_BASE_URL/--base-url points to the right server. User: {username}. "
            f"Status: {status_code}. Response: {payload}"
        )
    return payload["access"]


def checkout(base_url, token, fail_after_stock=False):
    headers = {"Authorization": f"Bearer {token}"}
    if fail_after_stock:
        headers[FAILURE_HEADER] = "1"
    return post_json(f"{base_url}/api/orders/checkout/", {}, headers=headers, timeout=30)


def capture_state(user, product):
    product.refresh_from_db()
    order_ids = list(Order.objects.filter(user=user).values_list("id", flat=True))
    cart_quantity = (
        CartItem.objects.filter(cart__user=user).aggregate(total=Sum("quantity")).get("total") or 0
    )
    return {
        "user_id": user.id,
        "username": user.username,
        "product_id": product.id,
        "product_name": product.name,
        "product_stock": product.stock,
        "cart_item_count": CartItem.objects.filter(cart__user=user).count(),
        "cart_quantity": cart_quantity,
        "order_count": len(order_ids),
        "order_item_count": OrderItem.objects.filter(order_id__in=order_ids).count(),
        "payment_count": Payment.objects.filter(order_id__in=order_ids).count(),
        "background_task_count": OrderBackgroundTask.objects.filter(order_id__in=order_ids).count(),
    }


def build_success_case(response_status, response_payload, duration_ms, initial_state, final_state, quantity):
    checks = {
        "checkout_returned_201": response_status == 201,
        "stock_reduced": final_state["product_stock"] == initial_state["product_stock"] - quantity,
        "cart_cleared": final_state["cart_item_count"] == 0 and final_state["cart_quantity"] == 0,
        "order_created": final_state["order_count"] == initial_state["order_count"] + 1,
        "order_item_created": final_state["order_item_count"] == initial_state["order_item_count"] + 1,
        "payment_created": final_state["payment_count"] == initial_state["payment_count"] + 1,
    }
    return {
        "status_code": response_status,
        "response": response_payload,
        "duration_ms": duration_ms,
        "checks": checks,
        "passed": all(checks.values()),
    }


def build_rollback_case(response_status, response_payload, duration_ms, initial_state, final_state):
    checks = {
        "checkout_failed": response_status >= 500,
        "stock_unchanged": final_state["product_stock"] == initial_state["product_stock"],
        "cart_unchanged": (
            final_state["cart_item_count"] == initial_state["cart_item_count"]
            and final_state["cart_quantity"] == initial_state["cart_quantity"]
        ),
        "no_order_created": final_state["order_count"] == initial_state["order_count"],
        "no_order_item_created": final_state["order_item_count"] == initial_state["order_item_count"],
        "no_payment_created": final_state["payment_count"] == initial_state["payment_count"],
        "no_background_task_created": (
            final_state["background_task_count"] == initial_state["background_task_count"]
        ),
    }
    return {
        "status_code": response_status,
        "response": response_payload,
        "duration_ms": duration_ms,
        "checks": checks,
        "passed": all(checks.values()),
    }


def build_result(success_case, rollback_case, initial_state, final_state):
    passed = bool(success_case.get("passed") and rollback_case.get("passed"))
    return {
        "success_case": success_case,
        "rollback_case": rollback_case,
        "initial_state": initial_state,
        "final_state": final_state,
        "result": "PASSED" if passed else "FAILED",
        "passed": passed,
        "debug_failure_enabled": bool(settings.DEBUG or getattr(settings, "TESTING", False)),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }


def save_results(result):
    results_dir = BASE_DIR / "results" / "acid"
    results_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    timestamped_path = results_dir / f"task8_acid_transaction_{timestamp}.json"
    latest_path = results_dir / "task8_acid_transaction_latest.json"

    for path in (timestamped_path, latest_path):
        path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")

    return timestamped_path, latest_path


def print_summary(result, latest_path):
    print("\nTask 8 - ACID Transaction Proof\n")
    print(f"Success case passed: {'Yes' if result['success_case']['passed'] else 'No'}")
    print(f"Rollback case passed: {'Yes' if result['rollback_case']['passed'] else 'No'}")
    print(f"Debug failure injection enabled: {'Yes' if result['debug_failure_enabled'] else 'No'}")
    print(f"Result: {result['result']}")
    print(f"\nSaved latest result: {latest_path}")


def main():
    args = parse_args()
    base_url = normalize_base_url(args.base_url)

    try:
        get_status(f"{base_url}/api/health/")
        cleanup_previous_data()

        success_user, success_product = create_fixture("success", args.stock, args.quantity)
        success_initial = capture_state(success_user, success_product)
        success_token = obtain_token(base_url, success_user.username)
        success_status, success_payload, success_duration_ms = checkout(base_url, success_token)
        success_final = capture_state(success_user, success_product)
        success_case = build_success_case(
            success_status,
            success_payload,
            success_duration_ms,
            success_initial,
            success_final,
            args.quantity,
        )

        rollback_user, rollback_product = create_fixture("rollback", args.stock, args.quantity)
        rollback_initial = capture_state(rollback_user, rollback_product)
        rollback_token = obtain_token(base_url, rollback_user.username)
        rollback_status, rollback_payload, rollback_duration_ms = checkout(
            base_url,
            rollback_token,
            fail_after_stock=True,
        )
        rollback_final = capture_state(rollback_user, rollback_product)
        rollback_case = build_rollback_case(
            rollback_status,
            rollback_payload,
            rollback_duration_ms,
            rollback_initial,
            rollback_final,
        )

        result = build_result(
            success_case=success_case,
            rollback_case=rollback_case,
            initial_state={"success_case": success_initial, "rollback_case": rollback_initial},
            final_state={"success_case": success_final, "rollback_case": rollback_final},
        )
        result["api_base_url"] = base_url
        result["failure_header"] = FAILURE_HEADER

        timestamped_path, latest_path = save_results(result)
        print_summary(result, latest_path)
        print(f"Saved timestamped result: {timestamped_path}")
        return 0 if result["passed"] else 1
    except AcidTransactionTestError as exc:
        print(f"\nTask 8 ACID transaction proof could not run: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
