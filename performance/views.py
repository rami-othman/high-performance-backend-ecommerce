import os
import socket
import threading

from django.conf import settings
from django.utils import timezone
from rest_framework.permissions import AllowAny, IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from .capacity_limiter import CheckoutCapacityUnavailable, get_checkout_capacity_metrics
from .models import PerformanceLog
from .serializers import PerformanceLogSerializer


class PerformanceLogListView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        logs = PerformanceLog.objects.all()[:200]
        serializer = PerformanceLogSerializer(logs, many=True)
        return Response(serializer.data)


class CapacityMetricsView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        try:
            return Response(get_checkout_capacity_metrics())
        except CheckoutCapacityUnavailable:
            return Response(
                {"detail": "Checkout capacity metrics are unavailable."},
                status=503,
            )


class HealthView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        response = Response(
            {
                "status": "ok",
                "server_name": settings.SERVER_NAME,
                "hostname": socket.gethostname(),
                "timestamp": timezone.now().isoformat(),
            }
        )
        response["X-Backend-Server"] = settings.SERVER_NAME
        return response


class ServerInfoView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        response = Response(
            {
                "server_name": settings.SERVER_NAME,
                "hostname": socket.gethostname(),
                "process_id": os.getpid(),
                "thread_id": threading.get_ident(),
                "timestamp": timezone.now().isoformat(),
            }
        )
        response["X-Backend-Server"] = settings.SERVER_NAME
        return response
