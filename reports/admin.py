from django.contrib import admin

from .models import DailySalesBatchRun, DailySalesReport


@admin.register(DailySalesReport)
class DailySalesReportAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "date",
        "total_orders",
        "total_order_items",
        "total_quantity_sold",
        "total_sales",
        "best_selling_product",
        "created_at",
    )
    list_filter = ("date",)


@admin.register(DailySalesBatchRun)
class DailySalesBatchRunAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "report_date",
        "status",
        "chunk_size",
        "chunks_processed",
        "total_orders",
        "total_sales",
        "duration_ms",
        "created_at",
    )
    list_filter = ("status", "report_date")
    search_fields = ("celery_task_id", "error_message")
