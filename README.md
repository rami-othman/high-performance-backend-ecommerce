# High-Performance E-Commerce Backend Engine

A monolithic Django backend for a Parallel Programming university project. The base system models an e-commerce workflow and is prepared for later experiments in concurrent access, locking, resource control, asynchronous queues, batch processing, load distribution, Redis caching, stress testing, and benchmarking.

## Course Goal

The project starts with a clean, correct backend foundation before adding performance experiments. The most important early goal is to make the core business flow deterministic and easy to test under load, especially checkout stock updates.

## Technology Stack

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

## Architecture

This is a monolithic Django project with separate domain apps. It is not a microservices system.

- `config`: settings, URLs, WSGI/ASGI, Celery app
- `products`: product catalog and stock
- `cart`: one cart per user and cart items
- `orders`: checkout, orders, order items, transaction boundary
- `payments`: payment records created during checkout
- `reports`: daily sales report model and batch processing task
- `performance`: request duration logging and health/server info endpoints

## JWT Authentication

API authentication uses SimpleJWT. The main API authentication class is `JWTAuthentication`, with `BasicAuthentication` kept available for simple manual testing.

JWT endpoints:

| Method | Endpoint | Purpose |
| --- | --- | --- |
| POST | `/api/auth/register/` | Create a default Django user and return tokens |
| POST | `/api/auth/token/` | Login and return access/refresh tokens |
| POST | `/api/auth/token/refresh/` | Refresh an expired access token |
| GET | `/api/auth/me/` | Return the current authenticated user |

Registration accepts:

```json
{
  "username": "student",
  "email": "student@example.com",
  "password": "strong-password"
}
```

The response includes `user`, `access`, and `refresh`. API POST requests should use JWT instead of browser session auth, which avoids the Swagger CSRF issue from session-authenticated POST requests.

## Database Tables

- `products_product`: product catalog, stock, version field
- `cart_cart`: one-to-one cart for each user
- `cart_cartitem`: product quantities in a cart
- `orders_order`: order header with total and status
- `orders_orderitem`: immutable checkout line items
- `orders_orderbackgroundtask`: persistent Celery task status proof for order background work
- `payments_payment`: one payment per order
- `reports_dailysalesreport`: daily aggregate sales results
- `reports_dailysalesbatchrun`: persistent chunked batch processing proof rows
- `performance_performancelog`: API/UI request timing logs
- Django default auth/session/admin tables

## API Endpoints

| Method | Endpoint | Purpose |
| --- | --- | --- |
| POST | `/api/auth/register/` | Register user and return JWT tokens |
| POST | `/api/auth/token/` | Login and return JWT tokens |
| POST | `/api/auth/token/refresh/` | Refresh JWT access token |
| GET | `/api/auth/me/` | Current authenticated user |
| GET | `/api/products/` | List products |
| GET | `/api/products/{id}/` | Product detail |
| GET | `/api/cart/` | Current user's cart |
| POST | `/api/cart/items/` | Add item to cart |
| PATCH | `/api/cart/items/{id}/` | Update cart item |
| DELETE | `/api/cart/items/{id}/` | Delete cart item |
| POST | `/api/orders/checkout/` | Transactional checkout |
| GET | `/api/orders/` | List current user's orders |
| GET | `/api/orders/{id}/` | Current user's order detail |
| POST | `/api/reports/daily-sales/run/` | Dispatch daily sales report task |
| GET | `/api/reports/daily-sales/batch-runs/{id}/` | Inspect one daily sales batch run |
| GET | `/api/reports/daily-sales/` | List daily sales reports |
| GET | `/api/performance/logs/` | List recent performance logs |
| GET | `/api/performance/capacity/` | Admin checkout capacity metrics |
| GET | `/api/health/` | Health check |
| GET | `/api/server-info/` | Return server name and hostname |
| GET | `/api/schema/` | OpenAPI schema |
| GET | `/api/docs/` | Swagger UI |

Admin-only endpoints currently use DRF `IsAdminUser`. Cart and order endpoints require authentication.

## Simple UI Pages

- `/` redirects to `/ui/dashboard/`
- `/ui/register/`
- `/ui/login/`
- `/ui/products/`
- `/ui/cart/`
- `/ui/orders/`
- `/ui/dashboard/`
- `/ui/logout/`

The UI uses Django templates, Bootstrap CDN, vanilla JavaScript, `fetch()`, and JWT tokens stored in `localStorage`. It is intentionally simple because the backend APIs are the main project surface.

## Run Locally With Conda

Create and activate your Conda environment outside the project directory:

```bash
conda create -n ecommerce-backend python=3.11
conda activate ecommerce-backend
pip install -r requirements.txt
```

Create a local environment file:

```bash
copy .env.example .env
```

On macOS/Linux, use:

```bash
cp .env.example .env
```

Make sure PostgreSQL and Redis are running locally, then update `.env` if your credentials differ.

Run migrations:

```bash
python manage.py makemigrations
python manage.py migrate
```

Create an admin user:

```bash
python manage.py createsuperuser
```

Seed sample products:

```bash
python scripts/seed_data.py
```

Start Django:

```bash
python manage.py runserver
```

Start Celery in another terminal:

```bash
celery -A config worker --loglevel=info
```

Open Swagger:

```text
http://127.0.0.1:8000/api/docs/
```

## Use JWT In Swagger

1. Open `http://127.0.0.1:8000/api/docs/`.
2. Call `POST /api/auth/token/` with a username and password, or call `POST /api/auth/register/`.
3. Copy the returned `access` token.
4. Click **Authorize** in Swagger.
5. Enter:

```text
Bearer <access_token>
```

6. Use authenticated endpoints such as `/api/cart/`, `/api/cart/items/`, and `/api/orders/checkout/`.

## Test The Web UI Flow

1. Open `http://127.0.0.1:8000/ui/register/`.
2. Create a user.
3. The browser saves JWT tokens in `localStorage` and redirects to `/ui/products/`.
4. Add products to the cart.
5. Open `/ui/cart/`.
6. Update quantities or remove items if needed.
7. Click checkout.
8. View created orders at `/ui/orders/`.

## Task 1 - Concurrent Access & Data Integrity

Task 1 proves that checkout protects shared inventory data when many users buy the same product at the same time.

Chosen approach:

- Pessimistic locking
- `transaction.atomic()`
- PostgreSQL row-level locks with `select_for_update()`

Key files:

- `orders/views.py`: checkout transaction, cart lock, product row locks, stock update, and post-commit Celery dispatch
- `scripts/race_condition_test.py`: HTTP concurrency proof script
- `docs/TASK_1_CONCURRENT_ACCESS.md`: report-ready explanation for Task 1

Run the proof script while the Django server is already running:

```bash
python scripts/race_condition_test.py
```

Optional configuration:

```bash
python scripts/race_condition_test.py --users 20 --stock 5 --quantity 1
API_BASE_URL=http://127.0.0.1:8000 python scripts/race_condition_test.py
```

Expected default result:

- Initial stock: `5`
- Concurrent users: `20`
- Successful checkouts: `5`
- Failed checkouts: `15`
- Final stock: `0`
- Negative stock: `No`
- Overselling: `No`
- Result: `PASSED`

The script saves proof output in `results/race_condition_task1_latest.json` and a timestamped JSON file.

## Task 2 - Resource Management & Capacity Control

Task 2 proves that checkout controls parallel work instead of allowing unlimited concurrent checkout operations to reach the database.

Chosen approach:

- Redis-backed active checkout counter
- Configurable checkout concurrency limit
- Clean `429` overload response when the limit is reached
- DRF scoped throttling for auth, cart, checkout, and reports
- Gunicorn `gthread` workers so the web container can process enough parallel requests to exercise the limiter

Key files:

- `performance/capacity_limiter.py`: Redis-backed checkout capacity limiter and metrics helpers
- `orders/views.py`: checkout capacity wrapper around the existing transactional checkout
- `scripts/resource_capacity_test.py`: HTTP concurrency proof script
- `scripts/start_web.sh`: Docker web startup with configurable Gunicorn concurrency
- `docs/PROJECT_DOCUMENTATION.md`: main report documentation, including Task 2

Run the proof script while the Django server is already running:

```bash
python scripts/resource_capacity_test.py
```

Docker example:

```bash
docker compose up --build
docker compose exec web python scripts/resource_capacity_test.py
```

The Docker web container runs Gunicorn with `gthread`, `WEB_CONCURRENCY=8`, and `GUNICORN_THREADS=2` by default. That gives an effective request capacity of `16`, which is intentionally higher than `CHECKOUT_MAX_CONCURRENT_REQUESTS=5` so the Redis limiter can reject overload during the proof.

Expected default result:

- Configured checkout limit: `5`
- Concurrent users: `20`
- Initial stock: `100`
- Max observed active checkouts: `> 1` and `<= 5`
- Capacity rejections: greater than `0`
- Server errors: `0`
- Result: `PASSED`

The proof script uses the `X-Capacity-Test-Delay` header only in `DEBUG=True` proof/demo mode so concurrent requests overlap reliably. The script saves proof output in `results/resource_capacity/resource_capacity_task2_latest.json` and a timestamped JSON file.

## Task 3 - Asynchronous Queues

Task 3 proves that checkout only performs critical ACID work synchronously. Slow non-critical work is moved to Celery so the user does not wait for invoice generation or order notification handling.

Chosen approach:

- Celery worker with Redis as broker/result backend
- `transaction.on_commit()` to enqueue work only after the order transaction commits
- Persistent `OrderBackgroundTask` rows for `queued`, `started`, `success`, and `failure` proof
- Worker-side demo delay controlled by environment settings, capped at three seconds

Key files:

- `orders/tasks.py`: measurable invoice and notification Celery tasks
- `orders/views.py`: post-commit task dispatch and queued task log creation
- `orders/models.py`: `OrderBackgroundTask` proof model
- `scripts/async_queue_test.py`: HTTP proof script for non-blocking checkout
- `docs/TASK_3_ASYNC_QUEUES.md`: report-ready Task 3 explanation

Redis acts as the Celery queue broker. Checkout creates the order, order items, payment, stock updates, and cart clear inside `transaction.atomic()`. After commit, the post-commit callback enqueues `generate_invoice_task` and `send_order_notification_task`. If a background task fails, the order and payment remain valid because invoice/notification work is outside the ACID checkout transaction.

Docker:

```bash
docker compose up --build
docker compose exec web python scripts/async_queue_test.py
```

Local:

```bash
python manage.py runserver
```

In another terminal:

```bash
celery -A config worker --loglevel=info
```

Run:

```bash
python scripts/async_queue_test.py
```

Expected default result:

- Checkout status: `201`
- Background tasks created: `2`
- Successful background tasks: `2`
- Failed background tasks: `0`
- Checkout duration is less than total background duration
- Checkout returned before background tasks finished
- Result: `PASSED`

The script saves proof output in `results/async_queues/async_queue_task3_latest.json` and a timestamped JSON file.

## Task 4 - Batch Processing

Task 4 proves that daily sales reporting runs as a background batch job and processes orders in controlled chunks instead of loading the whole day into memory.

Chosen approach:

- Celery worker with Redis as the broker
- Keyset pagination by `Order.id`
- Configurable chunk size
- `DailySalesBatchRun` rows for technical proof
- `DailySalesReport` rows for final business totals

Key files:

- `reports/tasks.py`: chunked daily sales Celery task
- `reports/models.py`: `DailySalesReport` and `DailySalesBatchRun`
- `reports/views.py`: authenticated API trigger endpoint
- `scripts/batch_processing_test.py`: HTTP and database proof script
- `docs/TASK_4_BATCH_PROCESSING.md`: report-ready Task 4 explanation

The batch job fetches only a page of order IDs at a time:

```text
Order.objects
  .filter(created_at__date=report_date, id__gt=last_id)
  .order_by("id")[:chunk_size]
```

Each chunk is aggregated separately. The task records chunk counts, quantities, sales totals, and duration in `DailySalesBatchRun.metadata["chunks"]`, then merges partial totals into one `DailySalesReport`.

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

Expected default result:

- API trigger status: `202`
- Generated orders: `250`
- Chunk size: `50`
- Expected chunks: `5`
- Actual chunks processed: `5`
- Batch status: `success`
- Report totals correct
- Result: `PASSED`

The script saves proof output in `results/batch_processing/batch_processing_task4_latest.json` and a timestamped JSON file.

## Task 5 - Load Distribution

Task 5 simulates horizontal request distribution while keeping the project as one monolithic Django application.

Chosen approach:

- HAProxy as the public HTTP load balancer
- Three identical Django backend containers: `web`, `web2`, and `web3`
- Round Robin load balancing
- Shared PostgreSQL database
- Shared Redis for capacity control, cache, Celery broker, and result backend
- Lightweight `/api/health/` checks for HAProxy
- `/api/server-info/` proof endpoint showing which backend handled a request

Round Robin is appropriate here because all three Django containers run the same image, use the same resources in this simulation, and handle similar short API requests. The app is stateless enough for this setup because JWT authentication is not stored in one web container, and durable/shared state lives in PostgreSQL and Redis.

The public API entrypoint is now:

```text
http://localhost:8000
```

That host port points to HAProxy, not directly to one Django container.

Docker:

```bash
docker compose up --build
docker compose exec web python scripts/load_distribution_test.py
```

From the host:

```bash
python scripts/load_distribution_test.py
```

Expected default result:

- Total requests: `60`
- Successful responses: `60`
- Failed responses: `0`
- Backend servers reached: `web-1`, `web-2`, `web-3`
- Unique backend servers reached: `3`
- Distribution reasonably balanced
- Result: `PASSED`

HAProxy stats are available at:

```text
http://localhost:8404/stats
```

The script saves proof output in `results/load_distribution/load_distribution_task5_latest.json` and a timestamped JSON file.

## Run With Docker

Create `.env` first:

```bash
copy .env.example .env
```

Start all services:

```bash
docker compose up --build
```

Run management commands in the web container:

```bash
docker compose exec web python manage.py createsuperuser
docker compose exec web python scripts/seed_data.py
```

Open:

```text
http://127.0.0.1:8000/
http://127.0.0.1:8000/api/docs/
```

## What Is Implemented

- Clean monolithic Django structure
- Domain apps for products, cart, orders, payments, reports, and performance
- Product read API
- JWT register, login, refresh, and current-user APIs
- Authenticated cart API
- Authenticated order API
- Checkout with `transaction.atomic()`
- User cart row locking with `select_for_update()` during checkout
- Product row locking with `select_for_update()` in deterministic `id` order during checkout
- Task 1 race-condition proof script for concurrent checkout
- Task 1 documentation for concurrent access and data integrity
- Redis-backed checkout capacity limiter
- DRF scoped throttling for auth, cart, checkout, and reports
- Configurable Gunicorn `gthread` web concurrency for capacity testing
- Task 2 resource capacity proof script
- Real Celery invoice and order notification tasks dispatched after checkout commit
- Persistent `OrderBackgroundTask` lifecycle rows for queued/started/success/failure task proof
- Task 3 asynchronous queue proof script
- Task 3 documentation for asynchronous queues
- Task 4 Celery daily sales batch processing with keyset chunking
- Persistent `DailySalesBatchRun` rows proving chunk size, chunk count, totals, and duration
- Task 4 batch processing proof script
- Task 4 documentation for chunked daily sales processing
- HAProxy load balancer with Round Robin distribution across `web`, `web2`, and `web3`
- Task 5 load distribution proof script
- Task 5 documentation for horizontal request distribution
- Main project documentation in `docs/PROJECT_DOCUMENTATION.md`
- Payment creation during checkout
- Cart clearing after checkout
- Daily sales report generation with merged chunk totals
- Basic automated checkout API test
- Redis configured as Celery broker, result backend, and Django cache backend
- Request duration middleware with database logging
- Health and server-info endpoints
- Swagger/OpenAPI docs
- Docker Compose with HAProxy, three Django web containers, PostgreSQL, Redis, and Celery
- Simple Django template pages
- Simple e-commerce UI that consumes the API with JWT and token refresh
- Seed data script
- Initial migrations for all domain apps

## TODO

- Expand automated tests for API behavior
- Implement Task 6 distributed Redis caching for product list/detail endpoints
- Add k6 stress tests
- Add benchmarking scripts and result documentation
- Add database indexes after observing query patterns
- Add stricter production settings

## Parallel Programming Coverage Plan

- Race Condition Protection: checkout locks the user's cart row inside `transaction.atomic()` before reading cart items, then locks product rows with `select_for_update()` in deterministic `id` order. Order invoice and notification Celery tasks are dispatched with `transaction.on_commit()` so workers only see committed orders. This prepares the project for checkout race-condition testing.
- Resource Management: checkout uses a Redis-backed active request counter to cap concurrent checkout operations, DRF scoped throttling for API protection, and Gunicorn `gthread` workers so the web runtime can handle enough parallel requests for the limiter proof.
- Queues: Celery uses Redis to run invoice generation and order notification work outside the checkout request path. `OrderBackgroundTask` records prove queued, started, success, and failure states.
- Batch Processing: Celery runs daily sales reports in chunks using keyset pagination by `Order.id`. `DailySalesBatchRun` records prove expected chunk count, actual chunks processed, and merged totals.
- Load Distribution: HAProxy distributes requests with Round Robin across `web-1`, `web-2`, and `web-3`. `/api/server-info/` proves which backend handled each request, and `/api/health/` supports HTTP health checks.
- Redis Cache: Task 6 is next. Settings include Redis cache; later product and report endpoints can cache expensive reads.
- Stress Testing: k6 will later simulate concurrent browse, cart, and checkout scenarios.
- Benchmarking: performance logs capture endpoint duration; later benchmark scripts can compare baseline vs optimized versions.

## Next Distributed Caching Step

Task 6 should add Redis-backed caching to selected read-heavy endpoints and prove the difference between uncached and cached responses without changing the monolithic architecture.
