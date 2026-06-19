from django.conf import settings
from django.core.cache import cache
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from performance.distributed_locks import (
    LOCK_WAITED,
    daily_sales_batch_run_detail_cache_rebuild_lock_key,
    daily_sales_reports_list_cache_rebuild_lock_key,
    redis_distributed_lock,
)
from products.cache_utils import (
    CACHE_HIT,
    CACHE_MISS,
    DAILY_SALES_BATCH_RUN_DETAIL_CACHE_TIMEOUT_SECONDS,
    DAILY_SALES_REPORTS_LIST_CACHE_KEY,
    DAILY_SALES_REPORTS_LIST_CACHE_TIMEOUT_SECONDS,
    daily_sales_batch_run_detail_cache_key,
    remember_daily_sales_batch_run_cache,
    set_cache_and_lock_headers,
    set_cache_header,
)
from .models import DailySalesBatchRun, DailySalesReport
from .serializers import (
    DailySalesBatchRequestSerializer,
    DailySalesBatchRunSerializer,
    DailySalesReportSerializer,
)
from .tasks import process_daily_sales_report_task


def cache_rebuild_busy_response(cache_key):
    return Response(
        {
            "code": "cache_rebuild_lock_busy",
            "detail": "Cache rebuild is already running. Try again shortly.",
            "cache_key": cache_key,
        },
        status=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


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
        cached_data = cache.get(DAILY_SALES_REPORTS_LIST_CACHE_KEY)
        if cached_data is not None:
            return set_cache_header(Response(cached_data), CACHE_HIT)

        with redis_distributed_lock(
            daily_sales_reports_list_cache_rebuild_lock_key(),
            timeout=10,
            blocking_timeout=2,
        ) as rebuild_lock:
            cached_data = cache.get(DAILY_SALES_REPORTS_LIST_CACHE_KEY)
            if cached_data is not None:
                lock_status = LOCK_WAITED if not rebuild_lock.acquired else rebuild_lock.status
                return set_cache_and_lock_headers(Response(cached_data), CACHE_HIT, lock_status)

            if not rebuild_lock.acquired:
                return cache_rebuild_busy_response(DAILY_SALES_REPORTS_LIST_CACHE_KEY)

            reports = DailySalesReport.objects.select_related("best_selling_product")
            serializer = DailySalesReportSerializer(reports, many=True)
            cache.set(
                DAILY_SALES_REPORTS_LIST_CACHE_KEY,
                serializer.data,
                timeout=DAILY_SALES_REPORTS_LIST_CACHE_TIMEOUT_SECONDS,
            )
            return set_cache_and_lock_headers(
                Response(serializer.data),
                CACHE_MISS,
                rebuild_lock.status,
            )


class DailySalesBatchRunDetailView(APIView):
    permission_classes = [IsAdminUser]
    throttle_scope = "reports"

    def get(self, request, batch_run_id):
        cache_key = daily_sales_batch_run_detail_cache_key(batch_run_id)
        cached_data = cache.get(cache_key)
        if cached_data is not None:
            return set_cache_header(Response(cached_data), CACHE_HIT)

        with redis_distributed_lock(
            daily_sales_batch_run_detail_cache_rebuild_lock_key(batch_run_id),
            timeout=10,
            blocking_timeout=2,
        ) as rebuild_lock:
            cached_data = cache.get(cache_key)
            if cached_data is not None:
                lock_status = LOCK_WAITED if not rebuild_lock.acquired else rebuild_lock.status
                return set_cache_and_lock_headers(Response(cached_data), CACHE_HIT, lock_status)

            if not rebuild_lock.acquired:
                return cache_rebuild_busy_response(cache_key)

            batch_run = get_object_or_404(DailySalesBatchRun.objects.select_related("report"), id=batch_run_id)
            serializer = DailySalesBatchRunSerializer(batch_run)
            cache.set(cache_key, serializer.data, timeout=DAILY_SALES_BATCH_RUN_DETAIL_CACHE_TIMEOUT_SECONDS)
            remember_daily_sales_batch_run_cache(batch_run_id)
            return set_cache_and_lock_headers(
                Response(serializer.data),
                CACHE_MISS,
                rebuild_lock.status,
            )
