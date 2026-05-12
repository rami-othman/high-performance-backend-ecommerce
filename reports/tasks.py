from django.db.models import Count, Sum
from django.utils import timezone
from celery import shared_task

from orders.models import Order, OrderItem
from .models import DailySalesReport


@shared_task
def process_daily_sales_report_task():
    report_date = timezone.localdate()
    orders = Order.objects.filter(created_at__date=report_date)
    total_orders = orders.count()
    total_sales = orders.aggregate(total=Sum("total_price"))["total"] or 0

    # This aggregate is intentionally simple and can later be replaced with chunked batch processing.
    best_seller = (
        OrderItem.objects.filter(order__created_at__date=report_date)
        .values("product")
        .annotate(total_quantity=Sum("quantity"))
        .order_by("-total_quantity")
        .first()
    )
    best_selling_product_id = best_seller["product"] if best_seller else None

    report, _ = DailySalesReport.objects.update_or_create(
        date=report_date,
        defaults={
            "total_orders": total_orders,
            "total_sales": total_sales,
            "best_selling_product_id": best_selling_product_id,
        },
    )
    print(f"Processed daily sales report {report.id} for {report_date}")
    return {"report_id": report.id, "date": str(report_date)}
