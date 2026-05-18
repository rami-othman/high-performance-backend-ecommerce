# Task 4 - Batch Processing

## 1. Requirement

Create a background job that performs daily sales processing and processes the data in chunks or batches to improve performance.

The proof must be measurable. For example, 250 orders with chunk size 50 should produce 5 processed chunks.

## 2. Problem Being Solved

Daily sales reporting can become expensive when the order table grows. A simple implementation that loads every order and order item for a day at once can use too much memory and can block a Django request worker.

Task 4 keeps the project monolithic but moves the heavy reporting work into a Celery worker and processes only a controlled number of orders per loop.

## 3. Why Aggregate-Only Processing Is Not Enough

A single aggregate query can calculate totals, but it does not prove batch processing. The task requirement is specifically to show that the system handles large daily sales data in controlled chunks and records how many chunks were processed.

The implementation still uses database aggregates, but only inside each chunk. The final result is created by merging partial totals from each chunk.

## 4. Architecture

- Django REST Framework exposes `POST /api/reports/daily-sales/run/`.
- PostgreSQL stores orders, order items, final reports, and batch proof rows.
- Redis acts as the Celery broker and result backend.
- Celery workers execute the chunked daily sales task.
- `DailySalesBatchRun` stores technical proof.
- `DailySalesReport` stores the final business report.

## 5. Batch Processing Flow

```text
Client/Admin
 -> POST /api/reports/daily-sales/run/
 -> Django creates DailySalesBatchRun
 -> Celery task queued in Redis
 -> Celery worker starts
 -> Orders selected by date
 -> Chunk 1 processed
 -> Chunk 2 processed
 -> ...
 -> Partial totals merged
 -> DailySalesReport updated
 -> DailySalesBatchRun marked success
```

## 6. Chunking Algorithm

The Celery task uses keyset pagination by `Order.id`:

```text
last_id = 0

while True:
    order_ids = Order.objects
        .filter(created_at__date=report_date, id__gt=last_id)
        .order_by("id")
        .values_list("id", flat=True)[:chunk_size]

    if not order_ids:
        break

    process only these order IDs
    last_id = order_ids[-1]
```

This avoids loading all orders at once. It also avoids offset pagination, where later pages become more expensive because the database must skip an increasing number of rows.

## 7. Data Recorded For Proof

`DailySalesBatchRun` records:

- `chunk_size`
- `chunks_processed`
- `total_orders`
- `total_order_items`
- `total_quantity_sold`
- `total_sales`
- `duration_ms`
- `metadata["chunks"]`
- `status`
- `celery_task_id`

Each chunk metadata entry records:

- chunk number
- first and last order ID
- order count
- order item count
- quantity sold
- chunk sales
- chunk duration

Money values in JSON metadata are stored as strings.

## 8. Proof Script

The proof script is:

```bash
python scripts/batch_processing_test.py
```

It performs these steps:

1. Creates isolated test data with `batch_processing_user_` usernames and `Batch Processing Test Product` product names.
2. Generates 250 orders by default.
3. Updates `Order.created_at` to an isolated report date.
4. Authenticates through `/api/auth/token/`.
5. Calls `POST /api/reports/daily-sales/run/`.
6. Polls `DailySalesBatchRun` until the Celery worker marks it `success`.
7. Verifies expected chunks, totals, report creation, metadata chunk details, and Celery task ID.
8. Saves JSON proof files under `results/batch_processing/`.

Docker:

```bash
docker compose up --build
docker compose exec web python scripts/batch_processing_test.py
```

Local:

```bash
python manage.py runserver
celery -A config worker --loglevel=info
python scripts/batch_processing_test.py
```

If the Celery worker is not running, the script fails clearly with:

```text
Start the Celery worker with docker compose up or celery -A config worker --loglevel=info
```

## 9. Expected Result

```text
Task 4 - Batch Processing Proof

Report date: 2001-01-15
Generated test orders: 250
Chunk size: 50
Expected chunks: 5
Actual chunks processed: 5
Total orders in batch: 250
Total quantity sold: XXX
Total sales: XXXX.XX
Total sales correct: Yes
DailySalesReport created: Yes
Celery task ID present: Yes
All chunks within chunk size: Yes
Batch status: success
Result: PASSED
```

## 10. Limitations And Future Improvements

- Schedule daily execution with Celery Beat.
- Export reports to CSV or PDF.
- Add a dashboard for batch runs.
- Add a retry strategy for transient failures.
- Add alerts on failed batch jobs.
