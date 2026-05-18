from django.urls import path

from .views import DailySalesBatchRunDetailView, DailySalesReportListView, DailySalesReportRunView


urlpatterns = [
    path("daily-sales/run/", DailySalesReportRunView.as_view(), name="daily-sales-run"),
    path(
        "daily-sales/batch-runs/<int:batch_run_id>/",
        DailySalesBatchRunDetailView.as_view(),
        name="daily-sales-batch-run-detail",
    ),
    path("daily-sales/", DailySalesReportListView.as_view(), name="daily-sales-list"),
]
