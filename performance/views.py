import os
import socket

from django.utils import timezone
from rest_framework.permissions import AllowAny, IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import PerformanceLog
from .serializers import PerformanceLogSerializer


class PerformanceLogListView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        logs = PerformanceLog.objects.all()[:200]
        serializer = PerformanceLogSerializer(logs, many=True)
        return Response(serializer.data)


class HealthView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"status": "ok", "timestamp": timezone.now().isoformat()})


class ServerInfoView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response(
            {
                "server_name": os.getenv("SERVER_NAME", "local-dev"),
                "hostname": socket.gethostname(),
            }
        )
