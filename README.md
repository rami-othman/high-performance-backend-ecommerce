# High-Performance E-Commerce Backend Engine

High-Performance E-Commerce Backend Engine is a Django monolithic backend built for a Parallel Programming university project. It models a realistic e-commerce workflow while focusing on non-functional requirements: concurrency correctness, resource control, queues, batch processing, load distribution, caching, distributed locks, ACID transactions, and stress testing.

The project uses PostgreSQL, Redis, Celery, HAProxy, and Docker Compose. The UI is intentionally simple because the main project value is in backend behavior and proof scripts, not frontend complexity.

## Current Status

- Tasks 1-9 are implemented.
- Each implemented task has a proof script, documentation, and generated result files under `results/`.
- Task 10, benchmark and bottleneck analysis, is still remaining.
- The final report is separate and can still be updated after Task 10.

## Quick Start with Docker

Create the environment file:

```bash
copy .env.example .env
```

On macOS/Linux:

```bash
cp .env.example .env
```

Start the full stack:

```bash
docker compose up -d --build
```

Create an admin user:

```bash
docker compose exec web python manage.py createsuperuser
```

Seed sample products:

```bash
docker compose exec web python scripts/seed_data.py
```

Useful URLs:

| URL | Purpose |
| --- | --- |
| `http://127.0.0.1:8000/` | Main app entrypoint through HAProxy |
| `http://127.0.0.1:8000/api/docs/` | Swagger/OpenAPI documentation |
| `http://127.0.0.1:8404/stats` | HAProxy stats page |

## Run All Automated Tests

Docker:

```bash
docker compose exec web python manage.py test
```

Local:

```bash
python manage.py test
```

## Proof Scripts by Task

Run proof scripts from Docker with:

```bash
docker compose exec web python <script_path>
```

| Task | Topic | Script | Documentation | Latest Result |
| --- | --- | --- | --- | --- |
| 1 | Concurrent access / race condition | `scripts/race_condition_test.py` | `docs/TASK_1_CONCURRENT_ACCESS.md` | `results/race_condition_task1_latest.json` |
| 2 | Resource management / capacity control | `scripts/resource_capacity_test.py` | `docs/PROJECT_DOCUMENTATION.md` or `docs/PROJECT_STATE.md` | `results/resource_capacity/resource_capacity_task2_latest.json` |
| 3 | Async queues | `scripts/async_queue_test.py` | `docs/TASK_3_ASYNC_QUEUES.md` | `results/async_queues/async_queue_task3_latest.json` |
| 4 | Batch processing | `scripts/batch_processing_test.py` | `docs/TASK_4_BATCH_PROCESSING.md` | `results/batch_processing/batch_processing_task4_latest.json` |
| 5 | Load distribution | `scripts/load_distribution_test.py` | `docs/TASK_5_LOAD_DISTRIBUTION.md` | `results/load_distribution/load_distribution_task5_latest.json` |
| 6 | Redis/Django cache in multiple places | `scripts/cache_test.py` | `docs/TASK_6_CACHING.md` | `results/cache/cache_task6_latest.json` |
| 7 | Redis distributed locks outside DB locks | `scripts/distributed_lock_test.py` | `docs/TASK_7_DISTRIBUTED_LOCKS.md` | `results/locks/task7_distributed_lock_latest.json` |
| 8 | ACID transaction integrity | `scripts/acid_transaction_test.py` | `docs/TASK_8_ACID_TRANSACTIONS.md` | `results/acid/task8_acid_transaction_latest.json` |
| 9 | 100-user stress testing across main operations | `scripts/stress_test_100_users.py` | `docs/TASK_9_STRESS_TESTING.md` | `results/stress/task9_stress_100_users_latest.json` |

### Docker Proof Commands

```bash
docker compose exec web python scripts/race_condition_test.py
docker compose exec web python scripts/resource_capacity_test.py
docker compose exec web python scripts/async_queue_test.py
docker compose exec web python scripts/batch_processing_test.py
docker compose exec web python scripts/load_distribution_test.py
docker compose exec web python scripts/cache_test.py
docker compose exec web python scripts/distributed_lock_test.py
docker compose exec web python scripts/acid_transaction_test.py
docker compose exec web python scripts/stress_test_100_users.py --base-url http://load_balancer --users 100
```

Task 9 should use `http://load_balancer` when run inside Docker so requests go through HAProxy instead of one Django container directly.

## Architecture Overview

This is a Django monolith with separated domain apps. It is not a microservices project.

| Path | Responsibility |
| --- | --- |
| `config` | Django settings, URL routing, ASGI/WSGI, Celery app, auth endpoints |
| `products` | Product catalog, stock data, product APIs, cache helpers |
| `cart` | User carts and cart item APIs |
| `orders` | Checkout, orders, order items, transaction boundary, async task registration |
| `payments` | Payment records created during checkout |
| `reports` | Daily sales reports and chunked batch processing |
| `performance` | Request timing middleware, capacity limiter metrics, health/server-info endpoints |
| `infra/haproxy` | HAProxy Round Robin load balancer configuration |
| `scripts` | Proof scripts, seed script, stress script |
| `docs` | Task documentation and project documentation |
| `results` | JSON and markdown proof outputs |

Shared infrastructure:

- PostgreSQL stores durable business data.
- Redis is used for cache, Celery broker/result backend, checkout capacity control, and distributed locks.
- Celery runs background invoice, notification, and batch-report work.
- HAProxy distributes HTTP traffic across `web`, `web2`, and `web3`.

## Main API Endpoints

| Area | Method | Endpoint | Purpose |
| --- | --- | --- | --- |
| Auth | `POST` | `/api/auth/register/` | Register user and return JWT tokens |
| Auth | `POST` | `/api/auth/token/` | Login and return JWT tokens |
| Auth | `POST` | `/api/auth/token/refresh/` | Refresh JWT access token |
| Auth | `GET` | `/api/auth/me/` | Current authenticated user |
| Products | `GET` | `/api/products/` | Product list, cached with `X-Cache` |
| Products | `GET` | `/api/products/{id}/` | Product detail, cached with `X-Cache` |
| Cart | `GET` | `/api/cart/` | Current user's cart |
| Cart | `POST` | `/api/cart/items/` | Add product to cart |
| Cart | `PATCH` | `/api/cart/items/{id}/` | Update cart item quantity |
| Cart | `DELETE` | `/api/cart/items/{id}/` | Remove cart item |
| Checkout | `POST` | `/api/orders/checkout/` | Transactional checkout |
| Orders | `GET` | `/api/orders/` | Current user's order history |
| Orders | `GET` | `/api/orders/{id}/` | Current user's order detail |
| Reports | `POST` | `/api/reports/daily-sales/run/` | Queue daily sales batch job |
| Reports | `GET` | `/api/reports/daily-sales/` | List daily sales reports |
| Reports | `GET` | `/api/reports/daily-sales/batch-runs/{id}/` | Inspect batch run details |
| Performance | `GET` | `/api/performance/logs/` | Recent request timing logs |
| Performance | `GET` | `/api/performance/capacity/` | Checkout capacity metrics |
| System | `GET` | `/api/health/` | Health check |
| System | `GET` | `/api/server-info/` | Backend server identity proof |
| Docs | `GET` | `/api/schema/` | OpenAPI schema |
| Docs | `GET` | `/api/docs/` | Swagger UI |

Admin-only endpoints use DRF `IsAdminUser`. Cart, checkout, and order endpoints require authentication. Product list/detail and health endpoints are public.

## Important Implementation Highlights

- Checkout uses `transaction.atomic()` and PostgreSQL `select_for_update()` locks for cart, cart items, and products.
- Product rows are locked in deterministic ID order to reduce deadlock risk.
- Redis checkout capacity limiter protects the checkout path from too many simultaneous active checkouts.
- Celery runs background invoice and order-notification tasks after checkout.
- `transaction.on_commit()` is used so Celery dispatch and cache invalidation only happen after a successful database commit.
- Daily sales reporting runs as chunked Celery batch processing.
- HAProxy provides Round Robin load distribution across three Django web containers.
- Redis/Django cache is used for read-heavy product and report endpoints, with `X-Cache: HIT` / `MISS` proof headers.
- Redis distributed locks protect cache rebuild and batch/report critical sections outside database row locks.
- Task 8 proves ACID rollback by injecting a debug-only checkout failure after stock reduction.
- Task 9 stress test simulates 100 users across auth/setup, products, cart, checkout, orders, reports, performance, and cached endpoints.
- Task 9 verifies stock, order, and payment integrity after the 100-user run.
- AOP-style performance logging middleware records request duration without mixing timing logic into each view.

## JWT Authentication Notes

API clients should send:

```text
Authorization: Bearer <access_token>
```

Swagger flow:

1. Open `http://127.0.0.1:8000/api/docs/`.
2. Call `POST /api/auth/token/` or `POST /api/auth/register/`.
3. Copy the returned `access` token.
4. Click **Authorize**.
5. Enter `Bearer <access_token>`.

## Simple UI Pages

The project includes simple Django template pages for manual demonstration:

| URL | Purpose |
| --- | --- |
| `/ui/register/` | Register |
| `/ui/login/` | Login |
| `/ui/products/` | Browse products |
| `/ui/cart/` | Manage cart |
| `/ui/orders/` | View orders |
| `/ui/dashboard/` | Dashboard |
| `/ui/logout/` | Logout |

The UI uses Bootstrap CDN, vanilla JavaScript, `fetch()`, and JWT tokens in `localStorage`.

## Local Development Without Docker

Create and activate a Python environment outside the repository:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

On macOS/Linux:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Create `.env`, then make sure PostgreSQL and Redis are running and match the `.env` settings.

Run:

```bash
python manage.py migrate
python manage.py createsuperuser
python scripts/seed_data.py
python manage.py runserver
```

Start Celery in another terminal:

```bash
celery -A config worker --loglevel=info
```

## Do Not Commit Local Files

Do not commit local environment, database, virtual environment, or generated Python cache files:

- `.env`
- `db.sqlite3`
- `venv/`
- `.venv/`
- `__pycache__/`
- `*.pyc`
- local logs or temporary run files

The repository `.gitignore` already covers these common local files.

## Remaining Work

Task 10 benchmark and bottleneck analysis is still remaining. After Task 10 is complete, the separate final report can be updated with the final benchmark tables, bottleneck discussion, and conclusion.
