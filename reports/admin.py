from django.contrib import admin

from .models import DailySalesReport


@admin.register(DailySalesReport)
class DailySalesReportAdmin(admin.ModelAdmin):
    list_display = ("id", "date", "total_orders", "total_sales", "best_selling_product", "created_at")
    list_filter = ("date",)
