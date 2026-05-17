from django.urls import path

from .views import CapacityMetricsView, PerformanceLogListView


urlpatterns = [
    path("logs/", PerformanceLogListView.as_view(), name="performance-logs"),
    path("capacity/", CapacityMetricsView.as_view(), name="performance-capacity"),
]
