from django.contrib import admin

from .models import Order, OrderBackgroundTask, OrderItem


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ("product", "quantity", "unit_price", "total_price")


class OrderBackgroundTaskInline(admin.TabularInline):
    model = OrderBackgroundTask
    extra = 0
    readonly_fields = (
        "task_name",
        "celery_task_id",
        "status",
        "started_at",
        "finished_at",
        "duration_ms",
        "message",
        "error_message",
        "metadata",
        "created_at",
        "updated_at",
    )
    can_delete = False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "total_price", "status", "created_at", "updated_at")
    search_fields = ("user__username",)
    list_filter = ("status", "created_at")
    inlines = [OrderItemInline, OrderBackgroundTaskInline]


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ("id", "order", "product", "quantity", "unit_price", "total_price")
    search_fields = ("product__name", "order__user__username")


@admin.register(OrderBackgroundTask)
class OrderBackgroundTaskAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "order",
        "task_name",
        "status",
        "celery_task_id",
        "duration_ms",
        "created_at",
        "updated_at",
    )
    list_filter = ("status", "task_name", "created_at")
    search_fields = ("order__id", "order__user__username", "task_name", "celery_task_id")
    readonly_fields = (
        "order",
        "task_name",
        "celery_task_id",
        "status",
        "started_at",
        "finished_at",
        "duration_ms",
        "message",
        "error_message",
        "metadata",
        "created_at",
        "updated_at",
    )
