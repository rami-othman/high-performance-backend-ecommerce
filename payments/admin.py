from django.contrib import admin

from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("id", "order", "amount", "status", "transaction_reference", "created_at")
    search_fields = ("transaction_reference", "order__user__username")
    list_filter = ("status", "created_at")
