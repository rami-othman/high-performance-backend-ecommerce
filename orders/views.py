from decimal import Decimal
from uuid import uuid4

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from cart.models import Cart
from payments.models import Payment
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

    def post(self, request):
        try:
            cart = Cart.objects.prefetch_related("items__product").get(user=request.user)
        except Cart.DoesNotExist:
            return Response({"detail": "Cart is empty."}, status=status.HTTP_400_BAD_REQUEST)

        cart_items = list(cart.items.all())
        if not cart_items:
            return Response({"detail": "Cart is empty."}, status=status.HTTP_400_BAD_REQUEST)

        product_ids = [item.product_id for item in cart_items]

        with transaction.atomic():
            # ACID boundary: every stock change, order row, payment row, and cart clear
            # succeeds or rolls back as one checkout operation.
            # Row-level locks protect product stock from concurrent checkout races.
            locked_products = {
                product.id: product
                for product in Product.objects.select_for_update().filter(id__in=product_ids).order_by("id")
            }

            total_price = Decimal("0.00")
            for item in cart_items:
                product = locked_products[item.product_id]
                if product.stock < item.quantity:
                    return Response(
                        {"detail": f"Not enough stock for {product.name}."},
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
                product.stock -= item.quantity
                product.version += 1
                product.save(update_fields=["stock", "version", "updated_at"])

            OrderItem.objects.bulk_create(order_items)

            Payment.objects.create(
                order=order,
                amount=total_price,
                status=Payment.Status.COMPLETED,
                transaction_reference=f"TXN-{uuid4().hex[:20].upper()}",
            )

            cart.items.all().delete()

            # Dispatch only after the database commit succeeds.
            transaction.on_commit(lambda order_id=order.id: dispatch_order_tasks(order_id))

        serializer = OrderSerializer(order)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


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
