from decimal import Decimal
import time
from uuid import uuid4

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
from products.models import Product
from .models import Order, OrderItem
from .serializers import OrderSerializer
from .tasks import generate_invoice_task, send_order_notification_task


def dispatch_order_tasks(order_id):
    try:
        generate_invoice_task.delay(order_id)
        send_order_notification_task.delay(order_id)
    except Exception as exc:
        print(f"Order {order_id} was saved, but task dispatch failed: {exc}")


class CheckoutView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = "checkout"

    def post(self, request):
        try:
            with CheckoutCapacityLimiter() as capacity:
                if not capacity.acquired:
                    return Response(
                        {
                            "detail": "Checkout service is busy. Please retry shortly.",
                            "code": "checkout_capacity_exceeded",
                        },
                        status=status.HTTP_429_TOO_MANY_REQUESTS,
                    )

                # Task 2 capacity proof hook: after a slot is acquired, a short
                # debug-only delay makes concurrent proof requests overlap. It is
                # capped at two seconds and disabled by default when DEBUG is false.
                apply_capacity_test_delay(request)
                return self.run_checkout(request)
        except CheckoutCapacityUnavailable:
            return Response(
                {
                    "detail": "Checkout capacity control is unavailable. Please retry shortly.",
                    "code": "checkout_capacity_unavailable",
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

    def run_checkout(self, request):
        with transaction.atomic():
            # ACID boundary: the cart read, stock validation, order creation,
            # payment creation, stock updates, and cart clear commit or roll back
            # as one checkout operation.
            try:
                # Synchronization point 1: lock this user's cart first. A duplicate
                # checkout request for the same user must wait here, then reread the
                # cart after the first request commits and clears it.
                cart = Cart.objects.select_for_update().get(user=request.user)
            except Cart.DoesNotExist:
                return Response({"detail": "Cart is empty."}, status=status.HTTP_400_BAD_REQUEST)

            # Cart items are read only after the cart lock is held, so concurrent
            # duplicate checkout requests cannot both use the same cart contents.
            cart_items = list(cart.items.select_related("product").all())
            if not cart_items:
                return Response({"detail": "Cart is empty."}, status=status.HTTP_400_BAD_REQUEST)

            product_ids = sorted({item.product_id for item in cart_items})

            # Synchronization point 2: lock product rows in deterministic id order.
            # This protects stock from many users buying the same products and helps
            # reduce deadlock risk when carts contain multiple products.
            locked_products = {
                product.id: product
                for product in Product.objects.select_for_update().filter(id__in=product_ids).order_by("id")
            }

            if len(locked_products) != len(product_ids):
                return Response(
                    {"detail": "One or more products in the cart are no longer available."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            total_price = Decimal("0.00")
            for item in cart_items:
                product = locked_products[item.product_id]
                if product.stock < item.quantity:
                    return Response(
                        {
                            "detail": (
                                f"Not enough stock for {product.name}. "
                                f"Available stock: {product.stock}."
                            )
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                total_price += product.price * item.quantity

            order = Order.objects.create(
                user=request.user,
                total_price=total_price,
                status=Order.Status.PAID,
            )

            order_items = []
            for item in cart_items:
                product = locked_products[item.product_id]
                line_total = product.price * item.quantity
                order_items.append(
                    OrderItem(
                        order=order,
                        product=product,
                        quantity=item.quantity,
                        unit_price=product.price,
                        total_price=line_total,
                    )
                )
                # Stock update: this mutation is safe because the Product row was
                # locked above with select_for_update() inside this transaction.
                product.stock -= item.quantity
                update_fields = ["stock", "updated_at"]
                if hasattr(product, "version"):
                    product.version += 1
                    update_fields.append("version")
                product.save(update_fields=update_fields)

            OrderItem.objects.bulk_create(order_items)

            Payment.objects.create(
                order=order,
                amount=total_price,
                status=Payment.Status.COMPLETED,
                transaction_reference=f"TXN-{uuid4().hex[:20].upper()}",
            )

            cart.items.all().delete()

            # Celery tasks are registered inside the transaction but dispatched only
            # after the database commit succeeds, so workers never see rolled-back
            # orders.
            transaction.on_commit(lambda order_id=order.id: dispatch_order_tasks(order_id))

        return Response(
            {
                "order_id": order.id,
                "total_price": str(order.total_price),
                "status": order.status,
                "message": "Checkout completed successfully.",
            },
            status=status.HTTP_201_CREATED,
        )


class OrderListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        orders = Order.objects.filter(user=request.user).prefetch_related("items__product")
        serializer = OrderSerializer(orders, many=True)
        return Response(serializer.data)


class OrderDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, order_id):
        order = get_object_or_404(
            Order.objects.prefetch_related("items__product").select_related("payment"),
            id=order_id,
            user=request.user,
        )
        serializer = OrderSerializer(order)
        return Response(serializer.data)


def apply_capacity_test_delay(request):
    if not (settings.DEBUG and settings.CHECKOUT_CAPACITY_TEST_DELAY_ENABLED):
        return

    raw_delay = request.headers.get("X-Capacity-Test-Delay")
    if not raw_delay:
        return

    try:
        delay_seconds = max(0.0, min(float(raw_delay), 2.0))
    except ValueError:
        return

    if delay_seconds:
        time.sleep(delay_seconds)
