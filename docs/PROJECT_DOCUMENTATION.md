# High-Performance E-Commerce Backend Engine - Project Documentation

## 1. Project Overview

High-Performance E-Commerce Backend Engine is a monolithic Django REST Framework backend for a Parallel Programming university project. The system models a simple e-commerce workflow with products, carts, checkout, payments, reports, JWT authentication, Redis, Celery, PostgreSQL, and a simple Django template UI.

The project focuses on non-functional behavior that can be demonstrated and measured: concurrent access safety, resource capacity control, asynchronous queues, batch processing, load distribution, caching, stress testing, and benchmarking.

## 2. Course Requirements Summary

The project is organized around these implementation tasks:

| Task   | Requirement                            | Current Status                  |
| ------ | -------------------------------------- | ------------------------------- |
| Task 1 | Concurrent Access & Data Integrity     | Implemented and provable        |
| Task 2 | Resource Management & Capacity Control | Implemented and provable        |
| Task 3 | Asynchronous Queues                    | Implemented and provable        |
| Task 4 | Batch Processing                       | Implemented and provable        |
| Task 5 | Load Distribution                      | Implemented and provable        |

## 3. Technology Stack

- Python 3.11
- Django
- Django REST Framework
- SimpleJWT
- PostgreSQL
- Redis
- Celery
- HAProxy
- Docker Compose
- drf-spectacular Swagger/OpenAPI
- Simple Django templates with Bootstrap and vanilla JavaScript

## 4. System Architecture

The system is intentionally monolithic. It uses separate Django apps for domain boundaries, not microservices.

- `config`: settings, root URLs, auth URLs, Celery setup
- `products`: product catalog and stock
- `cart`: user carts and cart items
- `orders`: checkout, orders, order items, transaction boundary
- `payments`: payment records created during checkout
- `reports`: daily sales report model, batch proof model, and chunked Celery task
- `performance`: request timing logs, health endpoints, server info, and capacity metrics

Redis is shared infrastructure for Celery, Django cache, DRF throttling, and the Task 2 checkout capacity limiter.

## 5. Database Design

Core tables:

| Table                          | Purpose                                                  |
| ------------------------------ | -------------------------------------------------------- |
| `products_product`           | Product catalog, price, stock, optimistic version marker |
| `cart_cart`                  | One cart per user                                        |
| `cart_cartitem`              | Product quantities selected by a user                    |
| `orders_order`               | Order header with total price and status                 |
| `orders_orderitem`           | Immutable checkout line items                            |
| `orders_orderbackgroundtask` | Persistent Celery task lifecycle proof rows              |
| `payments_payment`           | One payment record per order                             |
| `reports_dailysalesreport`   | Daily aggregate sales data                               |
| `reports_dailysalesbatchrun` | Technical proof for chunked daily sales batch jobs       |
| `performance_performancelog` | Request duration logging                                 |

The most important shared data item is `Product.stock`, because many users can try to buy the same product at the same time.

## 6. API Design

Main API endpoints:

| Method | Endpoint                       | Purpose                              |
| ------ | ------------------------------ | ------------------------------------ |
| POST   | `/api/auth/register/`        | Register and receive JWT tokens      |
| POST   | `/api/auth/token/`           | Login and receive JWT tokens         |
| POST   | `/api/auth/token/refresh/`   | Refresh JWT token                    |
| GET    | `/api/products/`             | List products                        |
| GET    | `/api/cart/`                 | Current user's cart                  |
| POST   | `/api/cart/items/`           | Add item to cart                     |
| POST   | `/api/orders/checkout/`      | Transactional checkout               |
| GET    | `/api/orders/`               | Current user's orders                |
| POST   | `/api/reports/daily-sales/run/` | Queue daily sales batch processing |
| GET    | `/api/reports/daily-sales/`  | List daily sales reports             |
| GET    | `/api/performance/capacity/` | Admin-only checkout capacity metrics |
| GET    | `/api/docs/`                 | Swagger UI                           |

JWT authentication remains the main API authentication method. Admin-only endpoints use DRF `IsAdminUser`.

## 7. Simple UI Flow

The UI is intentionally simple because the backend behavior is the main project focus.

User flow:

1. Register or log in at `/ui/register/` or `/ui/login/`.
2. JWT tokens are saved in browser `localStorage`.
3. Browse products at `/ui/products/`.
4. Add products to the cart.
5. Review cart at `/ui/cart/`.
6. Click checkout.
7. View created orders at `/ui/orders/`.

The Task 1 and Task 2 backend changes do not change this UI flow.

## 8. AOP / Performance Monitoring

The `performance.middleware.PerformanceLogMiddleware` records request duration into `performance_performancelog`. This acts as simple aspect-oriented monitoring because timing logic is applied around requests without being duplicated inside every API view.

Current monitoring endpoints:

- `GET /api/performance/logs/`
- `GET /api/health/`
- `GET /api/server-info/`
- `GET /api/performance/capacity/`

## 9. Task 1 - Concurrent Access & Data Integrity

Task 1 protects shared product stock from race conditions during checkout.

Chosen solution:

- Pessimistic locking
- `transaction.atomic()`
- PostgreSQL row-level locks using `select_for_update()`

Checkout synchronization:

1. Start a transaction.
2. Lock the user's cart.
3. Read cart items after the cart lock.
4. Lock required product rows in deterministic `id` order.
5. Validate stock before creating the order.
6. Create order and order items.
7. Reduce product stock while rows are locked.
8. Create payment.
9. Clear cart.
10. Dispatch Celery tasks only after commit.

Task 1 proof script:

```bash
python scripts/race_condition_test.py
```

Task 1 is isolated from the Task 2 capacity limiter. The script sends a DEBUG-only
`X-Race-Condition-Test-Capacity-Limit` header that raises the checkout capacity
limit for this proof run only, so all 20 checkout attempts can reach the
transactional stock locking and validation code. In production, the header is
ignored because the override requires `DEBUG=True`.

Default result table:

| Metric                      | Value  |
| --------------------------- | ------ |
| Initial stock               | 5      |
| Concurrent users            | 20     |
| Successful checkouts        | 5      |
| Failed checkouts            | 15     |
| Insufficient stock failures | 15     |
| Capacity rejections         | 0      |
| Server errors               | 0      |
| Final stock                 | 0      |
| Result                      | PASSED |

Conclusion: checkout protects `Product.stock` from overselling under concurrent requests.
The failed requests fail because stock is exhausted, not because Task 2 capacity
control rejected them.

## 10. Task 2 - Resource Management & Capacity Control

Task 2 controls how many checkout operations are allowed to run at the same time.

### Problem

Even when checkout is transactionally correct, too many concurrent checkout requests can overload the server or database. Without a capacity limit, every request can reach expensive database locks and transactions at the same time. That may increase latency, exhaust database connections, and make the application unstable.

The goal is not to block all parallelism. The goal is to allow a safe amount of parallel checkout work while rejecting excess requests cleanly.

### Chosen Solution

The project uses a Redis-backed checkout capacity limiter.

Key files:

- `performance/capacity_limiter.py`
- `orders/views.py`
- `scripts/resource_capacity_test.py`
- `scripts/start_web.sh`
- `docs/PROJECT_DOCUMENTATION.md`

Configuration:

| Setting                                  | Default                                           |
| ---------------------------------------- | ------------------------------------------------- |
| `CHECKOUT_MAX_CONCURRENT_REQUESTS`     | `5`                                             |
| `CHECKOUT_CAPACITY_KEY`                | `capacity:checkout:active`                      |
| `CHECKOUT_CAPACITY_TTL_SECONDS`        | `30`                                            |
| `CHECKOUT_CAPACITY_TEST_DELAY_ENABLED` | `True` when `DEBUG=True`, otherwise `False` |

Docker/Gunicorn runtime settings:

| Setting              | Default |
| -------------------- | ------- |
| `WEB_CONCURRENCY`  | `8`   |
| `GUNICORN_THREADS` | `2`   |
| `GUNICORN_TIMEOUT` | `120` |

The Docker web container uses Gunicorn `gthread` workers. The default effective request capacity is `WEB_CONCURRENCY * GUNICORN_THREADS = 16`, which is intentionally higher than the checkout limit of `5`. This matters for the proof: if Gunicorn runs with a single sync worker, requests are processed almost sequentially and the Redis limiter only observes one active checkout.

DRF scoped throttling is also configured:

| Scope        | Default Rate |
| ------------ | ------------ |
| `auth`     | `30/min`   |
| `cart`     | `120/min`  |
| `checkout` | `60/min`   |
| `reports`  | `20/min`   |

### Why Redis

Redis was chosen instead of a Python in-memory counter because Django can run with multiple processes or containers. A Python counter would only limit one process. Redis provides one shared counter across all Django workers, so the limit applies to the whole backend instance group.

### How The Limiter Works

For each checkout request:

1. The view tries to acquire a checkout slot before starting checkout work.
2. Redis atomically increments the active checkout counter.
3. Redis TTL is refreshed so a crashed process does not leave a permanent counter.
4. If the active count is above the configured limit, the counter is decremented immediately and the request is rejected.
5. If allowed, checkout runs normally.
6. A `finally` path releases the slot after checkout completes.
7. Redis also tracks `max_observed_active_checkouts` for proof.

For proof and demo only, the script sends `X-Capacity-Test-Delay`. In `DEBUG=True`, checkout sleeps briefly after acquiring a capacity slot and before entering the transaction. The delay is capped at two seconds and is disabled by default when `DEBUG=False`.

### Limit Reached Behavior

When the limit is reached, checkout returns:

```json
{
  "detail": "Checkout service is busy. Please retry shortly.",
  "code": "checkout_capacity_exceeded"
}
```

The response status is `429 Too Many Requests`. This is appropriate because the request is valid, but the service is temporarily refusing it due to capacity pressure.

If Redis is unavailable, checkout returns `503 Service Unavailable` instead of crashing with a server error.

### Proof Script

Run the proof script while the Django server is already running:

```bash
python scripts/resource_capacity_test.py
```

Default scenario:

- Configured checkout limit: `5`
- Concurrent users: `20`
- Initial stock: `100`
- Quantity per user: `1`

Expected:

- Max observed active checkouts is less than or equal to `5`.
- Max observed active checkouts is greater than `1`, proving real overlap reached Django.
- Some requests receive `429` capacity responses.
- Server errors are `0`.
- Final product stock is not negative.
- Total sold quantity does not exceed initial stock.

Result files:

```text
results/resource_capacity/resource_capacity_task2_latest.json
results/resource_capacity/resource_capacity_task2_YYYYMMDD_HHMMSS.json
```

Result table placeholder:

| Metric                        | Expected     |
| ----------------------------- | ------------ |
| Configured checkout limit     | 5            |
| Concurrent users              | 20           |
| Server errors                 | 0            |
| Max observed active checkouts | > 1 and <= 5 |
| Capacity rejections           | > 0          |
| Result                        | PASSED       |

Conclusion: the system controls checkout parallelism using Redis-backed capacity tracking and rejects overload cleanly.

## 11. Task 3 - Asynchronous Queues

Task 3 moves slow non-critical checkout work out of the HTTP request path.

### Problem

Users should not wait for work that is not required to complete the order. Invoice generation and order notification delivery can involve external systems, file generation, or email/SMS providers. If those operations run inside checkout, a slow provider makes checkout slow even though the order, payment, stock update, and cart clear are already complete.

### Chosen Solution

The project uses Celery workers with Redis as the queue broker. Checkout keeps only critical ACID work synchronous:

1. Lock cart and product rows.
2. Validate stock.
3. Create order and order items.
4. Reduce stock.
5. Create payment.
6. Clear cart.
7. Commit the PostgreSQL transaction.

After commit, `transaction.on_commit()` enqueues:

- `generate_invoice_task`
- `send_order_notification_task`

Key files:

- `orders/tasks.py`
- `orders/views.py`
- `orders/models.py`
- `scripts/async_queue_test.py`
- `results/async_queues/`

### Why This Is Asynchronous

The HTTP checkout response returns after the order transaction commits and the Celery messages are placed on Redis. The Celery worker runs invoice and notification work in a separate process. The user does not wait for the simulated invoice or notification delay.

### Correctness

`transaction.on_commit()` is important because workers must not see rolled-back orders. The callback is registered during checkout but runs only after PostgreSQL confirms the transaction committed. If checkout fails and rolls back, no invoice or notification task is queued for that failed order.

### Failure Isolation

Invoice and notification tasks are not part of the ACID checkout transaction. If a task fails, `OrderBackgroundTask.status` becomes `failure` and `error_message` records the exception, but the order and payment remain valid.

### Persistent Proof Model

`OrderBackgroundTask` records each background job:

| Field Group                                      | Purpose                                                     |
| ------------------------------------------------ | ----------------------------------------------------------- |
| `order`, `task_name`, `celery_task_id`     | Link the database proof row to the order and Celery message |
| `status`                                       | Tracks `queued`, `started`, `success`, or `failure` |
| `started_at`, `finished_at`, `duration_ms` | Measures worker-side execution time                         |
| `message`, `error_message`, `metadata`     | Stores task result details or failure information           |

The invoice task stores metadata such as invoice number, order total, item count, and generated timestamp. The notification task stores username, email, message type, and sent timestamp. No real PDF or email is produced in this phase.

### Proof

Run the proof script while Django and Celery are running:

```bash
python scripts/async_queue_test.py
```

Docker:

```bash
docker compose up --build
docker compose exec web python scripts/async_queue_test.py
```

Expected result table:

| Metric                                   | Expected |
| ---------------------------------------- | -------- |
| Checkout status                          | 201      |
| Background tasks                         | 2        |
| Successful tasks                         | 2        |
| Failed tasks                             | 0        |
| Celery task IDs present                  | Yes      |
| Checkout returned before task completion | Yes      |
| Result                                   | PASSED   |

The script writes:

```text
results/async_queues/async_queue_task3_latest.json
results/async_queues/async_queue_task3_YYYYMMDD_HHMMSS.json
```

Conclusion: checkout commits the order and returns before the slower invoice and notification work finishes in Celery.

## 12. Task 4 - Batch Processing

Task 4 processes daily sales data as a Celery background batch job.

### Requirement

Create a background job that performs daily sales processing and processes the data in chunks or batches to improve performance. The proof must show that a day with many orders is not loaded as one large in-memory operation.

### Problem

Processing large daily sales data in one request or one ORM load can be slow and memory-heavy. If the system loads all orders and all order items for a busy day at once, the request worker can block for a long time and memory usage grows with the size of the order table.

### Chosen Solution

The project uses a Celery background job with chunked processing:

1. An admin client calls `POST /api/reports/daily-sales/run/`.
2. Django validates `report_date` and `chunk_size`.
3. Django creates a queued `DailySalesBatchRun`.
4. The task is sent to Redis.
5. A Celery worker processes orders in chunks.
6. Chunk totals are merged into a final `DailySalesReport`.
7. The batch run is marked `success` or `failure`.

### Why Chunking Helps

Chunking controls memory usage because each loop only selects a limited list of order IDs and aggregates order items for those IDs. It also makes progress measurable: `DailySalesBatchRun.chunks_processed` and `metadata["chunks"]` show exactly how many chunks were processed and how many orders were inside each chunk.

The HTTP request only queues the work and returns `202 Accepted`. The expensive report generation happens in a Celery worker instead of blocking a Django request worker.

### Algorithm

The task uses keyset pagination by `Order.id`:

```text
last_id = 0

while True:
    order_ids = Order.objects
        .filter(created_at__date=report_date, id__gt=last_id)
        .order_by("id")
        .values_list("id", flat=True)[:chunk_size]

    if no order_ids:
        break

    process this chunk
    last_id = last order id in the chunk
```

Keyset pagination avoids loading all orders at once and avoids the growing database cost of large offset pagination.

### Data Flow

```text
API trigger
 -> DailySalesBatchRun queued
 -> Redis broker
 -> Celery worker
 -> chunk 1
 -> chunk 2
 -> ...
 -> partial totals merged
 -> DailySalesReport updated
 -> DailySalesBatchRun marked success
```

### Correctness

Each chunk calculates:

- orders in the chunk
- order items in the chunk
- quantity sold in the chunk
- sales total in the chunk
- per-product sold quantity for best-seller selection

The final report is not a separate unbounded load. It is built from the merged partial totals. The best-selling product is selected from accumulated per-product quantities across all chunks.

### Proof

The proof script is:

```bash
python scripts/batch_processing_test.py
```

Docker:

```bash
docker compose up --build
docker compose exec web python scripts/batch_processing_test.py
```

Expected proof output:

| Metric                  | Expected |
| ----------------------- | -------- |
| Generated test orders   | 250      |
| Chunk size              | 50       |
| Expected chunks         | 5        |
| Actual chunks processed | 5        |
| Batch status            | success  |
| Result                  | PASSED   |

The script writes JSON results to:

```text
results/batch_processing/batch_processing_task4_latest.json
results/batch_processing/batch_processing_task4_YYYYMMDD_HHMMSS.json
```

### Key Files

- `reports/models.py`
- `reports/tasks.py`
- `reports/views.py`
- `reports/serializers.py`
- `reports/urls.py`
- `scripts/batch_processing_test.py`
- `results/batch_processing/`

### Connection To Earlier Tasks

Task 3 proved that Celery and Redis can run asynchronous checkout background work. Task 4 uses the same queue infrastructure for a heavier daily sales job. Task 2 protects request capacity by limiting checkout concurrency; Task 4 protects background processing by avoiding one large memory-heavy report operation.

## 13. Task 5 - Load Distribution

Task 5 simulates distributing incoming HTTP requests across more than one backend server.

### Requirement

Simulate request distribution across multiple servers and explain the chosen distribution strategy.

### Problem

A single backend server can become a bottleneck under high traffic. Even if checkout is transactionally safe and async work is queued, one Django web container still has finite request capacity. The project needs to demonstrate that the request handling layer can be horizontally scaled while preserving shared state and correctness.

### Chosen Solution

The project uses three Django web containers behind HAProxy:

- `web` with `SERVER_NAME=web-1`
- `web2` with `SERVER_NAME=web-2`
- `web3` with `SERVER_NAME=web-3`

HAProxy is the single public entrypoint on `http://localhost:8000`. Each backend runs the same monolithic Django code and connects to the same PostgreSQL and Redis services.

### Strategy

HAProxy uses Round Robin:

```text
balance roundrobin
```

Round Robin was selected because the backend containers are homogeneous in this simulation. They run the same image, use the same configuration except `SERVER_NAME`, and handle similar short API requests. Sequential distribution is appropriate when servers have similar hardware and tasks take roughly similar time.

### Architecture

```text
Client
 -> HAProxy
 -> web-1 / web-2 / web-3
 -> shared PostgreSQL
 -> shared Redis
```

PostgreSQL remains the shared relational database. Redis remains the shared service for checkout capacity control, cache settings, Celery broker, and Celery result backend.

### Health Checks

HAProxy uses a lightweight L7 HTTP health check:

```text
GET /api/health/
```

The endpoint returns `200 OK`, server identity, hostname, and timestamp. It does not perform expensive database work.

### Statelessness

The web containers are stateless enough for load balancing:

- JWT authentication is carried by the request and is not stored inside one web container.
- Orders, products, carts, payments, reports, and users are stored in shared PostgreSQL.
- Checkout capacity control uses shared Redis, so the limit applies globally across web containers.
- Celery queues are external to web containers and use Redis.

This means any web container can handle any authenticated API request.

### Proof

The proof script is:

```bash
python scripts/load_distribution_test.py
```

Docker:

```bash
docker compose up --build
docker compose exec web python scripts/load_distribution_test.py
```

Expected proof:

| Metric                         | Expected                 |
| ------------------------------ | ------------------------ |
| Total requests                 | 60                       |
| Successful responses           | 60                       |
| Failed responses               | 0                        |
| Backend servers reached        | web-1, web-2, web-3      |
| Unique backend servers reached | 3                        |
| Strategy                       | Round Robin              |
| Result                         | PASSED                   |

The script writes:

```text
results/load_distribution/load_distribution_task5_latest.json
results/load_distribution/load_distribution_task5_YYYYMMDD_HHMMSS.json
```

### Key Files

- `docker-compose.yml`
- `infra/haproxy/haproxy.cfg`
- `config/settings.py`
- `performance/views.py`
- `performance/system_urls.py`
- `scripts/load_distribution_test.py`
- `results/load_distribution/`

### Connection To Earlier Tasks

Task 1 still protects stock when checkout requests hit different web containers because PostgreSQL row locks are shared. Task 2 still works globally because the capacity limiter uses shared Redis. Task 3 Celery queues remain external to web containers. Task 4 batch jobs remain background Celery work. Task 5 scales the request handling layer without changing the monolithic application.

## 14. Redis Caching Plan

To be completed in later phases.

Planned Task 6 focus: cache product list/detail responses and compare response duration before and after caching.

## 15. ACID Transaction Safety

Checkout uses `transaction.atomic()` so order creation, order items, stock reduction, payment creation, cart clearing, and post-commit task registration are coordinated safely. If any database write fails, the transaction rolls back.

## 16. Stress Testing Plan

To be completed in later phases.

Planned focus: use k6 or Python scripts to generate repeatable load scenarios for product browsing, cart updates, checkout, capacity limiting, and reporting.

## 17. Benchmarking Plan

To be completed in later phases.

Planned focus: compare baseline and optimized versions using response time, throughput, error rate, database consistency, and server resource usage.

## 18. Final Demo Scenario

The final demo should show:

1. Register/login with JWT.
2. Browse products and add to cart.
3. Run Task 1 race-condition proof.
4. Run Task 2 resource-capacity proof.
5. Run Task 3 asynchronous-queue proof.
6. Run Task 4 batch-processing proof.
7. Run Task 5 load-distribution proof.
8. Show performance logs, capacity metrics, batch runs, daily sales reports, and HAProxy stats.
9. Demonstrate later caching and benchmarking tasks as they are completed.

## 19. Conclusion

The project now has a correct transactional checkout foundation, a race-condition proof for shared stock, a Redis-backed capacity limiter that prevents excessive checkout parallelism, Celery-backed asynchronous queue proof for non-critical checkout work, chunked Celery batch processing for daily sales reports, and HAProxy Round Robin distribution across three Django web containers. The remaining phases will extend the system with distributed caching, stress testing, and benchmark documentation.
