from rest_framework import serializers

from products.serializers import ProductSerializer
from .models import DailySalesBatchRun, DailySalesReport


class DailySalesReportSerializer(serializers.ModelSerializer):
    best_selling_product_detail = ProductSerializer(source="best_selling_product", read_only=True)

    class Meta:
        model = DailySalesReport
        fields = [
            "id",
            "date",
            "total_orders",
            "total_order_items",
            "total_quantity_sold",
            "total_sales",
            "best_selling_product",
            "best_selling_product_detail",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class DailySalesBatchRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = DailySalesBatchRun
        fields = [
            "id",
            "report_date",
            "status",
            "celery_task_id",
            "chunk_size",
            "chunks_processed",
            "total_orders",
            "total_order_items",
            "total_quantity_sold",
            "total_sales",
            "started_at",
            "finished_at",
            "duration_ms",
            "metadata",
            "error_message",
            "report",
        ]
        read_only_fields = fields


class DailySalesBatchRequestSerializer(serializers.Serializer):
    report_date = serializers.DateField(required=False)
    chunk_size = serializers.IntegerField(required=False, min_value=1, max_value=1000)
