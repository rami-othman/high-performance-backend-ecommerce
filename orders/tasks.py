from celery import shared_task


@shared_task
def generate_invoice_task(order_id):
    print(f"Generating invoice for order {order_id}")
    return {"order_id": order_id, "status": "invoice-placeholder-generated"}


@shared_task
def send_order_notification_task(order_id):
    print(f"Sending order notification for order {order_id}")
    return {"order_id": order_id, "status": "notification-placeholder-sent"}
