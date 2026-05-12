from rest_framework import serializers

from .models import PerformanceLog


class PerformanceLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = PerformanceLog
        fields = ["id", "endpoint", "method", "status_code", "duration_ms", "created_at"]
        read_only_fields = fields
