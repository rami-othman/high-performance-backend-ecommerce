from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import DailySalesBatchRun, DailySalesReport
from .serializers import (
    DailySalesBatchRequestSerializer,
    DailySalesBatchRunSerializer,
    DailySalesReportSerializer,
)
from .tasks import process_daily_sales_report_task


class DailySalesReportRunView(APIView):
    permission_classes = [IsAdminUser]
    throttle_scope = "reports"

    def post(self, request):
        serializer = DailySalesBatchRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        report_date = serializer.validated_data.get("report_date") or timezone.localdate()
        chunk_size = serializer.validated_data.get(
            "chunk_size",
            settings.DAILY_SALES_BATCH_CHUNK_SIZE,
        )
        batch_run = DailySalesBatchRun.objects.create(
            report_date=report_date,
            chunk_size=chunk_size,
            status=DailySalesBatchRun.Status.QUEUED,
            metadata={"chunks": [], "algorithm": "keyset_pagination_by_order_id"},
        )
        task = process_daily_sales_report_task.delay(
            report_date=str(report_date),
            batch_run_id=batch_run.id,
            chunk_size=chunk_size,
        )
        batch_run.celery_task_id = task.id
        batch_run.save(update_fields=["celery_task_id", "updated_at"])

        return Response(
            {
                "detail": "Daily sales batch processing queued.",
                "batch_run_id": batch_run.id,
                "report_date": str(report_date),
                "chunk_size": chunk_size,
                "celery_task_id": task.id,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class DailySalesReportListView(APIView):
    permission_classes = [IsAdminUser]
    throttle_scope = "reports"

    def get(self, request):
        reports = DailySalesReport.objects.select_related("best_selling_product")
        serializer = DailySalesReportSerializer(reports, many=True)
        return Response(serializer.data)


class DailySalesBatchRunDetailView(APIView):
    permission_classes = [IsAdminUser]
    throttle_scope = "reports"

    def get(self, request, batch_run_id):
        batch_run = get_object_or_404(DailySalesBatchRun.objects.select_related("report"), id=batch_run_id)
        serializer = DailySalesBatchRunSerializer(batch_run)
        return Response(serializer.data)
