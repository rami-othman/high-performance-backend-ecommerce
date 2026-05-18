from django.conf import settings
from django.db import models

from products.models import Product


def default_daily_sales_chunk_size():
    return getattr(settings, "DAILY_SALES_BATCH_CHUNK_SIZE", 100)


class DailySalesReport(models.Model):
    date = models.DateField(unique=True)
    total_orders = models.PositiveIntegerField(default=0)
    total_order_items = models.PositiveIntegerField(default=0)
    total_quantity_sold = models.PositiveIntegerField(default=0)
    total_sales = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    best_selling_product = models.ForeignKey(
        Product,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="daily_sales_reports",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date"]

    def __str__(self):
        return f"Daily sales report for {self.date}"


class DailySalesBatchRun(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        STARTED = "started", "Started"
        SUCCESS = "success", "Success"
        FAILURE = "failure", "Failure"

    report_date = models.DateField()
    report = models.ForeignKey(
        DailySalesReport,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="batch_runs",
    )
    celery_task_id = models.CharField(max_length=255, null=True, blank=True, db_index=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    chunk_size = models.PositiveIntegerField(default=default_daily_sales_chunk_size)
    chunks_processed = models.PositiveIntegerField(default=0)
    total_orders = models.PositiveIntegerField(default=0)
    total_order_items = models.PositiveIntegerField(default=0)
    total_quantity_sold = models.PositiveIntegerField(default=0)
    total_sales = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Daily sales batch for {self.report_date} ({self.status})"
