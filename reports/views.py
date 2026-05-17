from rest_framework import status
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import DailySalesReport
from .serializers import DailySalesReportSerializer
from .tasks import process_daily_sales_report_task


class DailySalesReportRunView(APIView):
    permission_classes = [IsAdminUser]
    throttle_scope = "reports"

    def post(self, request):
        task = process_daily_sales_report_task.delay()
        return Response({"task_id": task.id}, status=status.HTTP_202_ACCEPTED)


class DailySalesReportListView(APIView):
    permission_classes = [IsAdminUser]
    throttle_scope = "reports"

    def get(self, request):
        reports = DailySalesReport.objects.select_related("best_selling_product")
        serializer = DailySalesReportSerializer(reports, many=True)
        return Response(serializer.data)
