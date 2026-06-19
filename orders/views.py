from decimal import Decimal
import time
from uuid import uuid4
import redis

from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from cart.models import Cart
from payments.models import Payment
from performance.capacity_limiter import CheckoutCapacityLimiter, CheckoutCapacityUnavailable
from products.cache_utils import invalidate_checkout_related_caches
from products.models import Product
from .models import Order, OrderBackgroundTask, OrderItem
from .serializers import OrderSerializer
from .tasks import generate_invoice_task, send_order_notification_task


RACE_CONDITION_TEST_CAPACITY_LIMIT_HEADER = "X-Race-Condition-Test-Capacity-Limit"

redis_client = redis.Redis.from_url(settings.REDIS_URL)


def dispatch_order_tasks(order_id):
    task_specs = [
        ("generate_invoice_task", generate_invoice_task),
        ("send_order_notification_task", send_order_notification_task),
    ]

    for task_name, task_func in task_specs:
        task_log = None
        try:
            task_log = OrderBackgroundTask.objects.create(
                order_id=order_id,
                task_name=task_name,
                status=OrderBackgroundTask.Status.QUEUED,
                message="Background task queued after checkout commit.",
            )
            async_result = task_func.delay(order_id, background_task_id=task_log.id)
            task_log.celery_task_id = async_result.id
            task_log.save(update_fields=["celery_task_id", "updated_at"])
        except Exception as exc:
            if task_log is not None:
                task_log.status = OrderBackgroundTask.Status.FAILURE
                task_log.message = "Background task dispatch failed after checkout commit."
                task_log.error_message = str(exc)
                task_log.save(update_fields=["status", "message", "error_message", "updated_at"])


class CheckoutView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = "checkout"

    def post(self, request):
        with CheckoutCapacityLimiter(limit=get_checkout_capacity_limit(request)) as capacity:
            if not capacity.acquired:
                return Response({"detail": "Busy"}, status=status.HTTP_429_TOO_MANY_REQUESTS)

            apply_capacity_test_delay(request)
            return self.run_checkout(request)

    def run_checkout(self, request):

        lock = redis_client.lock(f"checkout_lock_{request.user.id}", timeout=10)

        with lock:
            with transaction.atomic():

                cart = Cart.objects.select_for_update().get(user=request.user)
                cart_items = list(cart.items.select_related("product").all())

                product_ids = sorted({i.product_id for i in cart_items})

                locked_products = {
                    p.id: p for p in Product.objects.select_for_update().filter(id__in=product_ids)
                }

                total_price = Decimal("0.00")

                for item in cart_items:
                    product = locked_products[item.product_id]
                    if product.stock < item.quantity:
                        return Response({"error": "Out of stock"}, status=400)

                    total_price += product.price * item.quantity

                order = Order.objects.create(
                    user=request.user,
                    total_price=total_price,
                    status=Order.Status.PAID,
                )

                order_items = []

                for item in cart_items:
                    product = locked_products[item.product_id]

                    order_items.append(
                        OrderItem(
                            order=order,
                            product=product,
                            quantity=item.quantity,
                            unit_price=product.price,
                            total_price=product.price * item.quantity,
                        )
                    )

                    product.stock -= item.quantity
                    product.save(update_fields=["stock"])

                OrderItem.objects.bulk_create(order_items)

                Payment.objects.create(
                    order=order,
                    amount=total_price,
                    status=Payment.Status.COMPLETED,
                    transaction_reference=f"TXN-{uuid4().hex[:20].upper()}",
                )

                cart.items.all().delete()

                changed_product_ids = list(product_ids)
                transaction.on_commit(
                    lambda product_ids=changed_product_ids: invalidate_checkout_related_caches(product_ids)
                )
                transaction.on_commit(lambda: dispatch_order_tasks(order.id))

        return Response(
            {
                "order_id": order.id,
                "total_price": str(total_price),
                "status": order.status,
                "message": "Checkout completed successfully.",
                "background_tasks_dispatched": True,
            },
            status=status.HTTP_201_CREATED,
        )


class OrderListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        orders = Order.objects.filter(user=request.user)
        return Response(OrderSerializer(orders, many=True).data)


class OrderDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, order_id):
        order = get_object_or_404(Order, id=order_id, user=request.user)
        return Response(OrderSerializer(order).data)


def apply_capacity_test_delay(request):
    if settings.DEBUG and getattr(settings, "CHECKOUT_CAPACITY_TEST_DELAY_ENABLED", False):
        delay = request.headers.get("X-Capacity-Test-Delay")
        if delay:
            time.sleep(min(float(delay), 2))


def get_checkout_capacity_limit(request):
    if settings.DEBUG and getattr(settings, "CHECKOUT_CAPACITY_TEST_LIMIT_OVERRIDE_ENABLED", False):
        raw_limit = request.headers.get(RACE_CONDITION_TEST_CAPACITY_LIMIT_HEADER)
        if raw_limit:
            try:
                requested_limit = int(raw_limit)
            except (TypeError, ValueError):
                return settings.CHECKOUT_MAX_CONCURRENT_REQUESTS
            max_limit = getattr(settings, "CHECKOUT_CAPACITY_TEST_LIMIT_MAX", 1000)
            return max(1, min(requested_limit, max_limit))

    return settings.CHECKOUT_MAX_CONCURRENT_REQUESTS
