import time

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from .models import Order, OrderBackgroundTask


def get_capped_demo_delay_seconds():
    if not getattr(settings, "ORDER_ASYNC_TASK_TEST_DELAY_ENABLED", False):
        return 0.0

    try:
        delay_seconds = float(getattr(settings, "ORDER_ASYNC_TASK_TEST_DELAY_SECONDS", 1.0))
    except (TypeError, ValueError):
        delay_seconds = 1.0
    return max(0.0, min(delay_seconds, 3.0))


def get_or_create_background_task(order_id, task_name, background_task_id=None):
    if background_task_id:
        return OrderBackgroundTask.objects.get(id=background_task_id, order_id=order_id)

    return OrderBackgroundTask.objects.create(
        order_id=order_id,
        task_name=task_name,
        status=OrderBackgroundTask.Status.QUEUED,
    )


def mark_task_started(task_log, celery_task_id):
    now = timezone.now()
    task_log.status = OrderBackgroundTask.Status.STARTED
    task_log.started_at = now
    task_log.celery_task_id = celery_task_id
    task_log.message = "Background task started."
    task_log.error_message = ""
    task_log.save(
        update_fields=[
            "status",
            "started_at",
            "celery_task_id",
            "message",
            "error_message",
            "updated_at",
        ]
    )


def mark_task_success(task_log, started_at, metadata, message):
    finished_at = timezone.now()
    duration_ms = int((finished_at - started_at).total_seconds() * 1000)
    task_log.status = OrderBackgroundTask.Status.SUCCESS
    task_log.finished_at = finished_at
    task_log.duration_ms = max(duration_ms, 0)
    task_log.message = message
    task_log.error_message = ""
    task_log.metadata = metadata
    task_log.save(
        update_fields=[
            "status",
            "finished_at",
            "duration_ms",
            "message",
            "error_message",
            "metadata",
            "updated_at",
        ]
    )


def mark_task_failure(task_log, started_at, exc):
    finished_at = timezone.now()
    duration_ms = int((finished_at - started_at).total_seconds() * 1000)
    task_log.status = OrderBackgroundTask.Status.FAILURE
    task_log.finished_at = finished_at
    task_log.duration_ms = max(duration_ms, 0)
    task_log.message = "Background task failed."
    task_log.error_message = str(exc)
    task_log.save(
        update_fields=[
            "status",
            "finished_at",
            "duration_ms",
            "message",
            "error_message",
            "updated_at",
        ]
    )


@shared_task(bind=True)
def generate_invoice_task(self, order_id, background_task_id=None):
    task_name = "generate_invoice_task"
    task_log = get_or_create_background_task(order_id, task_name, background_task_id)
    started_at = timezone.now()
    mark_task_started(task_log, self.request.id)

    try:
        delay_seconds = get_capped_demo_delay_seconds()
        if delay_seconds:
            time.sleep(delay_seconds)

        order = (
            Order.objects.select_related("user")
            .prefetch_related("items__product")
            .get(id=order_id)
        )
        items = list(order.items.all())
        metadata = {
            "order_id": order.id,
            "invoice_number": f"INV-{order.id}",
            "total_price": str(order.total_price),
            "items_count": len(items),
            "generated_at": timezone.now().isoformat(),
        }
        mark_task_success(task_log, started_at, metadata, "Invoice metadata generated.")
        return {
            "status": OrderBackgroundTask.Status.SUCCESS,
            "task_name": task_name,
            "order_id": order.id,
            "background_task_id": task_log.id,
            "metadata": metadata,
        }
    except Exception as exc:
        mark_task_failure(task_log, started_at, exc)
        raise


@shared_task(bind=True)
def send_order_notification_task(self, order_id, background_task_id=None):
    task_name = "send_order_notification_task"
    task_log = get_or_create_background_task(order_id, task_name, background_task_id)
    started_at = timezone.now()
    mark_task_started(task_log, self.request.id)

    try:
        delay_seconds = get_capped_demo_delay_seconds()
        if delay_seconds:
            time.sleep(delay_seconds)

        order = Order.objects.select_related("user").get(id=order_id)
        metadata = {
            "order_id": order.id,
            "username": order.user.username,
            "email": order.user.email,
            "message_type": "order_confirmation",
            "sent_at": timezone.now().isoformat(),
        }
        mark_task_success(task_log, started_at, metadata, "Order confirmation notification simulated.")
        return {
            "status": OrderBackgroundTask.Status.SUCCESS,
            "task_name": task_name,
            "order_id": order.id,
            "background_task_id": task_log.id,
            "metadata": metadata,
        }
    except Exception as exc:
        mark_task_failure(task_log, started_at, exc)
        raise
