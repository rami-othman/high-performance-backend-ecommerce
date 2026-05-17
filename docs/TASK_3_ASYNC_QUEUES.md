# Task 3 - Asynchronous Queues

## 1. Requirement

Move non-critical checkout work outside the main HTTP request path while keeping the project as a monolithic Django application. Invoice generation and order notification work must run through real Celery + Redis queue behavior, not `CELERY_TASK_ALWAYS_EAGER=True`.

## 2. Problem Being Solved

Checkout should only make the user wait for work required to create a valid order: stock validation, stock update, order records, payment record, and cart cleanup. Invoice generation and notification sending can be slower because they often depend on external systems. Running them inside checkout would increase response time and make successful orders depend on non-critical work.

## 3. Architecture

The project keeps the monolithic Django architecture:

- Django REST Framework handles `POST /api/orders/checkout/`.
- PostgreSQL stores orders, payments, products, carts, and background task proof rows.
- Redis acts as the Celery broker and result backend.
- Celery workers execute invoice and notification tasks after checkout commits.
- `OrderBackgroundTask` records prove the lifecycle of each queued job.

## 4. Queue Flow Diagram

```text
Client
 -> POST /api/orders/checkout/
 -> Django checkout transaction
 -> PostgreSQL commit
 -> transaction.on_commit()
 -> Redis broker
 -> Celery worker
 -> invoice task / notification task
 -> OrderBackgroundTask status updated
```

## 5. Key Implementation Details

Key files:

- `orders/models.py`: adds `OrderBackgroundTask`.
- `orders/admin.py`: registers background task rows for admin inspection.
- `orders/views.py`: creates queued rows and dispatches Celery tasks after commit.
- `orders/tasks.py`: implements measurable bound Celery tasks.
- `scripts/async_queue_test.py`: proves checkout returns before background work finishes.
- `results/async_queues/`: stores JSON proof output.

`generate_invoice_task` loads the order and items, simulates invoice generation, and stores metadata with invoice number, total price, item count, and generation timestamp.

`send_order_notification_task` loads the order and user, simulates notification sending, and stores username, email, message type, and sent timestamp.

Both tasks use `@shared_task(bind=True)` so the Celery task ID can be stored in `OrderBackgroundTask.celery_task_id`.

## 6. Why `transaction.on_commit()` Is Important

The checkout transaction can still roll back if stock validation, order item creation, payment creation, or cart cleanup fails. Queueing a Celery task before commit would allow a worker to process an order that might never become durable.

`transaction.on_commit()` prevents that. The callback runs only after PostgreSQL commits the transaction. If checkout rolls back, no invoice or notification job is queued.

## 7. Why This Improves Performance

Checkout no longer waits for simulated invoice or notification work. The request commits the order and returns after the Celery messages are queued. The worker handles slower follow-up tasks in another process.

The proof script enables a short worker-side delay with:

```text
ORDER_ASYNC_TASK_TEST_DELAY_ENABLED=True
ORDER_ASYNC_TASK_TEST_DELAY_SECONDS=1.0
```

The delay is capped between `0` and `3` seconds and runs only inside Celery tasks, not inside checkout.

## 8. Proof Script

Run with Docker:

```bash
docker compose up --build
docker compose exec web python scripts/async_queue_test.py
```

Run locally:

```bash
python manage.py runserver
celery -A config worker --loglevel=info
python scripts/async_queue_test.py
```

The script:

1. Creates only `async_queue_user_*` test data and the `Async Queue Test Product`.
2. Authenticates through `/api/auth/token/`.
3. Calls `/api/orders/checkout/`.
4. Measures checkout duration.
5. Verifies order, payment, and stock state.
6. Polls `OrderBackgroundTask` rows until both tasks reach `success`.
7. Writes JSON results to `results/async_queues/`.

If the Celery worker is not running, the script times out clearly and prints:

```text
Start the Celery worker with docker compose up or celery -A config worker --loglevel=info
```

## 9. Expected Output

```text
Task 3 - Asynchronous Queues Proof

Checkout status: 201
Checkout duration: XXX ms
Background tasks created: 2
Successful background tasks: 2
Failed background tasks: 0
Task names:
- generate_invoice_task
- send_order_notification_task
Celery task IDs present: Yes
Total background duration: XXXX ms
Checkout returned before tasks finished: Yes
Result: PASSED
```

## 10. Limitations And Future Improvements

- Generate real PDF invoices instead of storing invoice metadata only.
- Send real email/SMS notifications through a provider.
- Add retry policy and dead-letter queue handling for permanent failures.
- Add a monitoring dashboard such as Flower or queue metrics in the admin UI.
