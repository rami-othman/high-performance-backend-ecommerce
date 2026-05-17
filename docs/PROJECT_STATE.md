# Project State: High-Performance E-Commerce Backend Engine

This file is intended to be pasted into a new ChatGPT or Codex chat so the project can continue with context.

## Project Summary

The project is a Parallel Programming university project named **High-Performance E-Commerce Backend Engine**. It is a clean monolithic Django backend for an e-commerce system. The current goal is to finish the base foundation first, not full optimization.

The future demonstrations will cover concurrent access and data integrity, resource management, asynchronous queues, batch processing, load distribution, Redis caching, concurrency control and locking, ACID transactions, stress testing, and benchmarking.

## Chosen Stack

- Python 3.11
- Django
- Django REST Framework
- djangorestframework-simplejwt
- PostgreSQL
- Redis
- Celery
- drf-spectacular for Swagger/OpenAPI
- Docker Compose
- Simple Django templates
- Django default `auth.User`

## Current Architecture

The architecture is a monolithic Django project with separate domain apps. It is intentionally not a microservices architecture.

- `config`: project settings, root URLs, WSGI/ASGI, Celery setup
- `products`: product catalog and stock tracking
- `cart`: user carts and cart items
- `orders`: transactional checkout and order records
- `payments`: payment record created by checkout
- `reports`: daily sales report model and Celery task placeholder
- `performance`: request timing middleware, logs, health, and server-info

JWT authentication is configured with SimpleJWT. API requests use `Authorization: Bearer <access_token>`. Basic authentication is still available for simple manual testing.

## File Structure

```text
high_performance_ecommerce/
|-- config/
|   |-- __init__.py
|   |-- auth_serializers.py
|   |-- auth_urls.py
|   |-- auth_views.py
|   |-- settings.py
|   |-- urls.py
|   |-- asgi.py
|   |-- wsgi.py
|   `-- celery.py
|-- products/
|   |-- migrations/0001_initial.py
|   |-- __init__.py
|   |-- admin.py
|   |-- apps.py
|   |-- models.py
|   |-- serializers.py
|   |-- urls.py
|   `-- views.py
|-- cart/
|   |-- migrations/0001_initial.py
|   |-- __init__.py
|   |-- admin.py
|   |-- apps.py
|   |-- models.py
|   |-- serializers.py
|   |-- urls.py
|   `-- views.py
|-- orders/
|   |-- migrations/0001_initial.py
|   |-- migrations/0002_orderbackgroundtask.py
|   |-- __init__.py
|   |-- admin.py
|   |-- apps.py
|   |-- models.py
|   |-- serializers.py
|   |-- tasks.py
|   |-- urls.py
|   `-- views.py
|-- payments/
|   |-- migrations/0001_initial.py
|   |-- __init__.py
|   |-- admin.py
|   |-- apps.py
|   `-- models.py
|-- reports/
|   |-- migrations/0001_initial.py
|   |-- __init__.py
|   |-- admin.py
|   |-- apps.py
|   |-- models.py
|   |-- serializers.py
|   |-- tasks.py
|   |-- urls.py
|   `-- views.py
|-- performance/
|   |-- migrations/0001_initial.py
|   |-- __init__.py
|   |-- admin.py
|   |-- apps.py
|   |-- capacity_limiter.py
|   |-- middleware.py
|   |-- models.py
|   |-- serializers.py
|   |-- system_urls.py
|   |-- urls.py
|   `-- views.py
|-- templates/
|   |-- ui/
|   |   |-- base.html
|   |   |-- register.html
|   |   |-- login.html
|   |   |-- products.html
|   |   |-- cart.html
|   |   |-- orders.html
|   |   |-- dashboard.html
|   |   `-- logout.html
|   |-- base.html
|   |-- home.html
|   |-- products.html
|   |-- cart.html
|   |-- orders.html
|   `-- dashboard.html
|-- docs/
|   |-- PROJECT_DOCUMENTATION.md
|   |-- PROJECT_STATE.md
|   |-- TASK_1_CONCURRENT_ACCESS.md
|   `-- TASK_3_ASYNC_QUEUES.md
|-- scripts/
|   |-- async_queue_test.py
|   |-- race_condition_test.py
|   |-- resource_capacity_test.py
|   |-- start_web.sh
|   `-- seed_data.py
|-- manage.py
|-- requirements.txt
|-- .env.example
|-- .gitignore
|-- Dockerfile
|-- docker-compose.yml
`-- README.md
```

## Apps Created

- `products`
- `cart`
- `orders`
- `payments`
- `reports`
- `performance`

## Models Created

### products.Product

- `name`
- `description`
- `price`
- `stock`
- `version`
- `created_at`
- `updated_at`

### cart.Cart

- `user`
- `created_at`
- `updated_at`

### cart.CartItem

- `cart`
- `product`
- `quantity`
- `created_at`
- `updated_at`

### orders.Order

- `user`
- `total_price`
- `status`
- `created_at`
- `updated_at`

### orders.OrderItem

- `order`
- `product`
- `quantity`
- `unit_price`
- `total_price`

### orders.OrderBackgroundTask

- `order`
- `task_name`
- `celery_task_id`
- `status`
- `started_at`
- `finished_at`
- `duration_ms`
- `message`
- `error_message`
- `metadata`
- `created_at`
- `updated_at`

### payments.Payment

- `order`
- `amount`
- `status`
- `transaction_reference`
- `created_at`

### reports.DailySalesReport

- `date`
- `total_orders`
- `total_sales`
- `best_selling_product`
- `created_at`

### performance.PerformanceLog

- `endpoint`
- `method`
- `status_code`
- `duration_ms`
- `created_at`

## Endpoints Created

### Auth API

- `POST /api/auth/register/`
- `POST /api/auth/token/`
- `POST /api/auth/token/refresh/`
- `GET /api/auth/me/`

### Product API

- `GET /api/products/`
- `GET /api/products/{id}/`

### Cart API

- `GET /api/cart/`
- `POST /api/cart/items/`
- `PATCH /api/cart/items/{id}/`
- `DELETE /api/cart/items/{id}/`

### Orders API

- `POST /api/orders/checkout/`
- `GET /api/orders/`
- `GET /api/orders/{id}/`

### Reports API

- `POST /api/reports/daily-sales/run/`
- `GET /api/reports/daily-sales/`

### Performance/System API

- `GET /api/performance/logs/`
- `GET /api/performance/capacity/`
- `GET /api/health/`
- `GET /api/server-info/`

### API Documentation

- `GET /api/schema/`
- `GET /api/docs/`

### Simple UI

- `/` redirects to `/ui/dashboard/`
- `/ui/register/`
- `/ui/login/`
- `/ui/products/`
- `/ui/cart/`
- `/ui/orders/`
- `/ui/dashboard/`
- `/ui/logout/`

Legacy simple pages still exist:

- `/products-ui/`
- `/cart-ui/`
- `/orders-ui/`
- `/dashboard/`

## Current Progress

The base Django project has been scaffolded. The domain apps, models, serializers, API views, URL routing, middleware, Celery setup, Docker Compose setup, templates, README, environment example, seed script, and initial migrations are in place.

JWT authentication has been added with SimpleJWT:

1. `POST /api/auth/register/` creates a default Django user and returns `user`, `access`, and `refresh`.
2. `POST /api/auth/token/` logs in and returns JWT tokens.
3. `POST /api/auth/token/refresh/` refreshes expired access tokens.
4. `GET /api/auth/me/` returns the current authenticated user's `id`, `username`, and `email`.

A simple Django template UI has been added under `/ui/`. It uses Bootstrap CDN, vanilla JavaScript, `fetch()`, and JWT tokens in `localStorage`. It supports registration, login, product browsing, add to cart, cart update/remove, checkout, order listing, dashboard, and logout. If an access token expires, the UI tries `/api/auth/token/refresh/` once before redirecting to login.

Checkout currently:

1. Enters `transaction.atomic()` before checkout reads or writes.
2. Locks the authenticated user's cart with `select_for_update()`.
3. Reads cart items only after the cart lock is held.
4. Locks selected product rows with `select_for_update()` in deterministic `id` order.
5. Validates that all products still exist and that stock is available.
6. Creates an order only after validation passes.
7. Creates order items.
8. Reduces product stock and increments product version.
9. Creates a completed payment record.
10. Clears the cart.
11. Dispatches real Celery invoice and notification tasks with `transaction.on_commit()` after the transaction succeeds.

This protects checkout from duplicate cart use and concurrent stock races while keeping non-critical invoice and notification work outside the request path.

## Task 1 - Concurrent Access & Data Integrity

Task 1 is now implemented and provable.

The chosen solution is pessimistic locking:

- `transaction.atomic()` wraps the checkout read/write flow.
- The user's cart row is locked with `select_for_update()` before cart items are read.
- Product rows are locked with `select_for_update()` in deterministic `id` order before stock validation and stock reduction.
- Celery invoice and notification tasks are registered with `transaction.on_commit()`.

The race condition proof script is:

```text
scripts/race_condition_test.py
```

The script uses Django ORM to create/reset only test data for `race_user_*` users and the Race Condition Test Product. It uses real HTTP requests to obtain JWT tokens and call `POST /api/orders/checkout/` concurrently.

Default proof scenario:

- Initial stock: `5`
- Concurrent users: `20`
- Quantity per user: `1`
- Expected successful checkouts: `5`
- Expected failed checkouts: `15`
- Expected final stock: `0`
- No negative stock
- No overselling

The Task 1 documentation is:

```text
docs/TASK_1_CONCURRENT_ACCESS.md
```

Result files are written to:

```text
results/race_condition_task1_latest.json
results/race_condition_task1_YYYYMMDD_HHMMSS.json
```

## Task 2 - Resource Management & Capacity Control

Task 2 is now implemented and provable.

The chosen solution is a Redis-backed checkout capacity limiter:

- `performance/capacity_limiter.py` keeps a shared active checkout counter in Redis.
- `orders/views.py` acquires a checkout capacity slot before running the existing transactional checkout.
- If the checkout limit is exceeded, the API returns `429` with code `checkout_capacity_exceeded`.
- If Redis is unavailable, checkout returns `503` instead of crashing with a server error.
- Capacity metrics are available at admin-only `GET /api/performance/capacity/`.
- DRF scoped throttling is configured for `auth`, `cart`, `checkout`, and `reports`.
- Docker web startup uses Gunicorn `gthread` workers through `scripts/start_web.sh`.
- Default web request capacity is `WEB_CONCURRENCY * GUNICORN_THREADS = 8 * 2 = 16`, which is higher than the checkout limit so the proof can produce real overlap and `429` overload responses.

Environment settings:

```text
CHECKOUT_MAX_CONCURRENT_REQUESTS=5
CHECKOUT_CAPACITY_KEY=capacity:checkout:active
CHECKOUT_CAPACITY_TTL_SECONDS=30
CHECKOUT_CAPACITY_TEST_DELAY_ENABLED=True when DEBUG=True, otherwise False
WEB_CONCURRENCY=8
GUNICORN_THREADS=2
GUNICORN_TIMEOUT=120
```

The resource capacity proof script is:

```text
scripts/resource_capacity_test.py
```

Default proof scenario:

- Configured checkout limit: `5`
- Concurrent users: `20`
- Initial stock: `100`
- Quantity per user: `1`
- Expected max observed active checkouts: `> 1` and `<= 5`
- Expected capacity rejections: greater than `0`
- Expected server errors: `0`
- Expected result: `PASSED`

The Task 2 proof originally showed `max_observed_active_checkouts=1` because the Docker web container was running Gunicorn with default single sync worker behavior. Task 2 proof was fixed by configuring Gunicorn concurrency with `gthread` workers and environment-driven worker/thread counts.

The main report documentation is:

```text
docs/PROJECT_DOCUMENTATION.md
```

Task 2 result files are written to:

```text
results/resource_capacity/resource_capacity_task2_latest.json
results/resource_capacity/resource_capacity_task2_YYYYMMDD_HHMMSS.json
```

## Task 3 - Asynchronous Queues

Task 3 is now implemented and provable.

The chosen solution is Celery with Redis as the broker:

- `orders/models.py` has `OrderBackgroundTask` for persistent DB logs.
- `orders/tasks.py` has bound Celery tasks for invoice generation and order notification simulation.
- `orders/views.py` creates queued task rows and dispatches tasks after checkout commit with `transaction.on_commit()`.
- `config/settings.py` has `ORDER_ASYNC_TASK_TEST_DELAY_ENABLED` and `ORDER_ASYNC_TASK_TEST_DELAY_SECONDS`.
- `.env.example` includes the async proof delay settings.
- `scripts/async_queue_test.py` proves checkout returns before background tasks finish.

The background task proof model records:

```text
queued -> started -> success
queued -> started -> failure
```

Each task stores the Celery task ID, start/end timestamps, duration, message, error message, and metadata. The invoice task records invoice metadata without writing a PDF. The notification task records simulated order confirmation metadata without sending a real email.

Task 3 result files are written to:

```text
results/async_queues/async_queue_task3_latest.json
results/async_queues/async_queue_task3_YYYYMMDD_HHMMSS.json
```

Task 3 documentation is:

```text
docs/TASK_3_ASYNC_QUEUES.md
```

## Next Tasks

1. Install dependencies in a Conda environment.
2. Create `.env` from `.env.example`.
3. Start PostgreSQL and Redis locally or use Docker Compose.
4. Run `python manage.py migrate`.
5. Create a superuser.
6. Seed sample products.
7. Test Swagger endpoints manually.
8. Test the full UI flow from `/ui/register/` to checkout.
9. Implement Task 4: Batch Processing.
10. Expand automated API tests.
11. Add Redis caching to product endpoints.
12. Add Nginx and multiple web replicas for load balancing.
13. Add k6 stress testing.
14. Add benchmarking scripts and write benchmark reports.

## Known Decisions

- Use Django default `auth.User`.
- Use monolithic Django architecture.
- Use PostgreSQL as the main relational database.
- Use Redis for cache and Celery broker/result backend.
- Use Celery for async jobs.
- Use SimpleJWT for API authentication.
- Use k6 later for stress testing.
- Use Nginx later for load balancing.
- Do not add a custom user model.
- Do not create microservices.
- Keep the first phase focused on the base foundation, not full optimization.

## Important Notes

The project is intentionally simple at this stage. Task 1 is implemented with the checkout transaction, cart lock, deterministic product locking, a race-condition proof script, and report-ready documentation. Task 2 is implemented with a Redis-backed checkout capacity limiter, scoped DRF throttling, capacity metrics, a resource capacity proof script, and main project documentation. Task 3 is implemented with Celery invoice/notification tasks, persistent `OrderBackgroundTask` logs, `transaction.on_commit()` dispatch, and an async queue proof script. The next non-functional requirement is Task 4 - Batch Processing. Performance logging is basic and database-backed so benchmarking can start early, but it may later need buffering or sampling to reduce overhead under heavy load.
