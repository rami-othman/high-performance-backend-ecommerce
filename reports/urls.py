from django.urls import path

from .views import DailySalesReportListView, DailySalesReportRunView


urlpatterns = [
    path("daily-sales/run/", DailySalesReportRunView.as_view(), name="daily-sales-run"),
    path("daily-sales/", DailySalesReportListView.as_view(), name="daily-sales-list"),
]
