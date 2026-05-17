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

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from cart.models import Cart, CartItem
from orders.models import Order, OrderBackgroundTask, OrderItem
from payments.models import Payment
from products.models import Product


DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_PRODUCT_NAME = "Async Queue Test Product"
ASYNC_USERNAME_PREFIX = "async_queue_user_"
ASYNC_PASSWORD = "AsyncQueuePassword123!"
EXPECTED_TASK_NAMES = {"generate_invoice_task", "send_order_notification_task"}
CELERY_WORKER_MESSAGE = (
    "Start the Celery worker with docker compose up or celery -A config worker --loglevel=info"
)


class AsyncQueueTestError(Exception):
    pass


def parse_args():
    parser = argparse.ArgumentParser(description="Task 3 asynchronous queue proof for checkout.")
    parser.add_argument(
        "--base-url",
        default=os.getenv("API_BASE_URL", DEFAULT_BASE_URL),
        help="Django API base URL. Defaults to API_BASE_URL or http://127.0.0.1:8000.",
    )
    parser.add_argument(
        "--product-name",
        default=DEFAULT_PRODUCT_NAME,
        help="Name of the test product to create or reset.",
    )
    parser.add_argument("--stock", type=int, default=5, help="Initial stock for the test product.")
    parser.add_argument("--quantity", type=int, default=1, help="Quantity to checkout.")
    parser.add_argument("--timeout", type=float, default=30.0, help="Seconds to wait for Celery task success.")
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
        raise AsyncQueueTestError(
            f"Could not connect to the Django API at {url}. "
            "Start the server and check API_BASE_URL or --base-url."
        ) from exc


def get_status(url, timeout=5):
    request = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status
    except urllib.error.URLError as exc:
        raise AsyncQueueTestError(
            f"Could not connect to the Django API at {url}. "
            "Start the server and check API_BASE_URL or --base-url."
        ) from exc


def cleanup_previous_test_data(product_name):
    User = get_user_model()
    User.objects.filter(username__startswith=ASYNC_USERNAME_PREFIX).delete()

    product = Product.objects.filter(name=product_name).order_by("id").first()
    if product is not None:
        duplicate_products = Product.objects.filter(name=product_name).exclude(id=product.id)
        for duplicate in duplicate_products:
            if not OrderItem.objects.filter(product=duplicate).exists():
                duplicate.delete()
    return product


def setup_test_data(initial_stock, quantity, product_name):
    if initial_stock < 1:
        raise AsyncQueueTestError("--stock must be at least 1.")
    if quantity < 1:
        raise AsyncQueueTestError("--quantity must be at least 1.")
    if quantity > initial_stock:
        raise AsyncQueueTestError("--quantity must be less than or equal to --stock.")

    try:
        with transaction.atomic():
            product = cleanup_previous_test_data(product_name)
            if product is None:
                product = Product.objects.create(
                    name=product_name,
                    description="Temporary product used by scripts/async_queue_test.py.",
                    price=Decimal("10.00"),
                    stock=initial_stock,
                )
            else:
                product.description = "Temporary product used by scripts/async_queue_test.py."
                product.price = Decimal("10.00")
                product.stock = initial_stock
                if hasattr(product, "version"):
                    product.version += 1
                    product.save(update_fields=["description", "price", "stock", "version", "updated_at"])
                else:
                    product.save(update_fields=["description", "price", "stock", "updated_at"])

            User = get_user_model()
            username = f"{ASYNC_USERNAME_PREFIX}{datetime.now().strftime('%Y%m%d%H%M%S')}"
            user = User.objects.create_user(
                username=username,
                email=f"{username}@example.com",
                password=ASYNC_PASSWORD,
            )
            cart = Cart.objects.create(user=user)
            CartItem.objects.create(cart=cart, product=product, quantity=quantity)
            return product, user
    except Exception as exc:
        raise AsyncQueueTestError(f"Database setup failed: {exc}") from exc


def obtain_token(base_url, username):
    status_code, payload, _ = post_json(
        f"{base_url}/api/auth/token/",
        {"username": username, "password": ASYNC_PASSWORD},
        timeout=15,
    )
    if status_code != 200 or "access" not in payload:
        raise AsyncQueueTestError(
            "JWT login failed. Check that the Django API is running and that "
            f"API_BASE_URL/--base-url points to the right server. User: {username}. "
            f"Status: {status_code}. Response: {payload}"
        )
    return payload["access"]


def checkout(base_url, token):
    return post_json(
        f"{base_url}/api/orders/checkout/",
        {},
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )


def serialize_task(task):
    return {
        "id": task.id,
        "order_id": task.order_id,
        "task_name": task.task_name,
        "celery_task_id": task.celery_task_id,
        "status": task.status,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "finished_at": task.finished_at.isoformat() if task.finished_at else None,
        "duration_ms": task.duration_ms,
        "message": task.message,
        "error_message": task.error_message,
        "metadata": task.metadata,
    }


def get_background_tasks(order_id):
    return list(OrderBackgroundTask.objects.filter(order_id=order_id).order_by("task_name"))


def wait_for_task_rows(order_id, timeout_seconds):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        tasks = get_background_tasks(order_id)
        if len(tasks) == 2:
            return tasks
        time.sleep(0.25)
    raise AsyncQueueTestError(
        f"Timed out waiting for two background task rows for order {order_id}. {CELERY_WORKER_MESSAGE}"
    )


def wait_for_task_success(order_id, timeout_seconds):
    deadline = time.monotonic() + timeout_seconds
    last_tasks = []
    while time.monotonic() < deadline:
        last_tasks = get_background_tasks(order_id)
        statuses = {task.status for task in last_tasks}
        if len(last_tasks) == 2 and statuses == {OrderBackgroundTask.Status.SUCCESS}:
            return last_tasks
        if OrderBackgroundTask.Status.FAILURE in statuses:
            return last_tasks
        time.sleep(0.5)

    serialized = [serialize_task(task) for task in last_tasks]
    raise AsyncQueueTestError(
        "Timed out waiting for both background tasks to reach success. "
        f"{CELERY_WORKER_MESSAGE}. Last task state: {serialized}"
    )


def verify_database_state(order_id, product, quantity):
    product.refresh_from_db()
    order_exists = Order.objects.filter(id=order_id, status=Order.Status.PAID).exists()
    payment_exists = Payment.objects.filter(order_id=order_id, status=Payment.Status.COMPLETED).exists()
    stock_reduced = product.stock == product._async_initial_stock - quantity
    return {
        "order_exists": order_exists,
        "payment_exists": payment_exists,
        "final_stock": product.stock,
        "stock_reduced": stock_reduced,
    }


def build_summary(
    checkout_status,
    checkout_duration_ms,
    background_tasks,
    order_exists,
    payment_exists,
    stock_reduced,
    checkout_returned_before_tasks_finished,
    server_error,
):
    task_names = sorted(task["task_name"] for task in background_tasks)
    background_task_count = len(background_tasks)
    successful_background_task_count = sum(1 for task in background_tasks if task["status"] == "success")
    failed_background_task_count = sum(1 for task in background_tasks if task["status"] == "failure")
    total_background_duration_ms = sum(task["duration_ms"] or 0 for task in background_tasks)
    celery_task_ids_present = all(bool(task["celery_task_id"]) for task in background_tasks)
    task_timestamps_present = all(task["started_at"] and task["finished_at"] for task in background_tasks)
    checkout_faster_than_background = checkout_duration_ms < total_background_duration_ms
    expected_tasks_present = set(task_names) == EXPECTED_TASK_NAMES
    passed = (
        checkout_status == 201
        and background_task_count == 2
        and successful_background_task_count == 2
        and failed_background_task_count == 0
        and celery_task_ids_present
        and task_timestamps_present
        and checkout_faster_than_background
        and checkout_returned_before_tasks_finished
        and order_exists
        and payment_exists
        and stock_reduced
        and not server_error
        and expected_tasks_present
    )

    return {
        "checkout_status": checkout_status,
        "checkout_duration_ms": checkout_duration_ms,
        "background_task_count": background_task_count,
        "successful_background_task_count": successful_background_task_count,
        "failed_background_task_count": failed_background_task_count,
        "total_background_duration_ms": total_background_duration_ms,
        "task_names": task_names,
        "celery_task_ids_present": celery_task_ids_present,
        "task_timestamps_present": task_timestamps_present,
        "checkout_returned_before_tasks_finished": checkout_returned_before_tasks_finished,
        "checkout_faster_than_background": checkout_faster_than_background,
        "order_exists": order_exists,
        "payment_exists": payment_exists,
        "stock_reduced": stock_reduced,
        "server_error": server_error,
        "passed": passed,
    }


def save_results(result):
    results_dir = BASE_DIR / "results" / "async_queues"
    results_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    timestamped_path = results_dir / f"async_queue_task3_{timestamp}.json"
    latest_path = results_dir / "async_queue_task3_latest.json"

    for path in (timestamped_path, latest_path):
        path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")

    return timestamped_path, latest_path


def print_summary(summary):
    print("\nTask 3 - Asynchronous Queues Proof\n")
    print(f"Checkout status: {summary['checkout_status']}")
    print(f"Checkout duration: {summary['checkout_duration_ms']} ms")
    print(f"Background tasks created: {summary['background_task_count']}")
    print(f"Successful background tasks: {summary['successful_background_task_count']}")
    print(f"Failed background tasks: {summary['failed_background_task_count']}")
    print("Task names:")
    for task_name in summary["task_names"]:
        print(f"- {task_name}")
    print(f"Celery task IDs present: {'Yes' if summary['celery_task_ids_present'] else 'No'}")
    print(f"Total background duration: {summary['total_background_duration_ms']} ms")
    print(
        "Checkout returned before tasks finished: "
        f"{'Yes' if summary['checkout_returned_before_tasks_finished'] else 'No'}"
    )
    print(f"Result: {'PASSED' if summary['passed'] else 'FAILED'}")


def main():
    args = parse_args()
    base_url = normalize_base_url(args.base_url)

    try:
        get_status(f"{base_url}/api/health/")
        product, user = setup_test_data(args.stock, args.quantity, args.product_name)
        product._async_initial_stock = args.stock
        token = obtain_token(base_url, user.username)

        checkout_started_at = timezone.now()
        checkout_status, checkout_payload, checkout_duration_ms = checkout(base_url, token)
        checkout_completed_at = timezone.now()
        server_error = checkout_status >= 500

        if checkout_status != 201:
            raise AsyncQueueTestError(
                f"Checkout did not return 201. Status: {checkout_status}. Response: {checkout_payload}"
            )

        order_id = checkout_payload.get("order_id")
        if not order_id:
            raise AsyncQueueTestError(f"Checkout response did not include order_id: {checkout_payload}")

        immediate_tasks = get_background_tasks(order_id)
        checkout_returned_before_tasks_finished = not (
            len(immediate_tasks) == 2
            and all(task.status == OrderBackgroundTask.Status.SUCCESS for task in immediate_tasks)
        )

        wait_for_task_rows(order_id, args.timeout)
        completed_tasks = wait_for_task_success(order_id, args.timeout)
        serialized_tasks = [serialize_task(task) for task in completed_tasks]
        latest_finished_at = max(task.finished_at for task in completed_tasks if task.finished_at)
        checkout_returned_before_tasks_finished = (
            checkout_returned_before_tasks_finished and latest_finished_at > checkout_completed_at
        )
        db_state = verify_database_state(order_id, product, args.quantity)
        summary = build_summary(
            checkout_status=checkout_status,
            checkout_duration_ms=checkout_duration_ms,
            background_tasks=serialized_tasks,
            order_exists=db_state["order_exists"],
            payment_exists=db_state["payment_exists"],
            stock_reduced=db_state["stock_reduced"],
            checkout_returned_before_tasks_finished=checkout_returned_before_tasks_finished,
            server_error=server_error,
        )
        result = {
            "api_base_url": base_url,
            "product_id": product.id,
            "product_name": product.name,
            "user_id": user.id,
            "username": user.username,
            "order_id": order_id,
            "checkout_response": checkout_payload,
            "checkout_started_at": checkout_started_at.isoformat(),
            "checkout_completed_at": checkout_completed_at.isoformat(),
            "summary": summary,
            "database_state": db_state,
            "background_tasks": serialized_tasks,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        timestamped_path, latest_path = save_results(result)
        print_summary(summary)
        print(f"\nSaved latest result: {latest_path}")
        print(f"Saved timestamped result: {timestamped_path}")
        return 0 if summary["passed"] else 1
    except AsyncQueueTestError as exc:
        print(f"\nTask 3 asynchronous queue proof could not run: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
