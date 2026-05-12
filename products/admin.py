from django.contrib import admin

from .models import Product


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "price", "stock", "version", "updated_at")
    search_fields = ("name",)
    list_filter = ("created_at", "updated_at")
