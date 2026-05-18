import time

from django.db import DatabaseError


class PerformanceLogMiddleware:
    SKIP_PATHS = {"/api/health/", "/api/server-info/"}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start = time.perf_counter()
        response = self.get_response(request)
        duration_ms = (time.perf_counter() - start) * 1000

        if request.path in self.SKIP_PATHS:
            return response

        try:
            from .models import PerformanceLog

            PerformanceLog.objects.create(
                endpoint=request.path[:255],
                method=request.method,
                status_code=response.status_code,
                duration_ms=duration_ms,
            )
        except DatabaseError:
            # During first migrations the table may not exist yet; request handling should continue.
            pass

        return response
