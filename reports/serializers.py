from rest_framework import serializers

from products.serializers import ProductSerializer
from .models import DailySalesReport


class DailySalesReportSerializer(serializers.ModelSerializer):
    best_selling_product_detail = ProductSerializer(source="best_selling_product", read_only=True)

    class Meta:
        model = DailySalesReport
        fields = [
            "id",
            "date",
            "total_orders",
            "total_sales",
            "best_selling_product",
            "best_selling_product_detail",
            "created_at",
        ]
        read_only_fields = fields
