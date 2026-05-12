from django.urls import path

from .views import PerformanceLogListView


urlpatterns = [
    path("logs/", PerformanceLogListView.as_view(), name="performance-logs"),
]
