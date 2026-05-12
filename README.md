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
- `reports`: daily sales report model and batch task placeholder
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
- `payments_payment`: one payment per order
- `reports_dailysalesreport`: daily aggregate sales results
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
| GET | `/api/reports/daily-sales/` | List daily sales reports |
| GET | `/api/performance/logs/` | List recent performance logs |
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
- Product row locking with `select_for_update()` during checkout
- Payment creation during checkout
- Cart clearing after checkout
- Placeholder Celery tasks for invoices, order notification, and daily sales report
- Redis configured as Celery broker, result backend, and Django cache backend
- Request duration middleware with database logging
- Health and server-info endpoints
- Swagger/OpenAPI docs
- Docker Compose with web, PostgreSQL, Redis, and Celery
- Simple Django template pages
- Simple e-commerce UI that consumes the API with JWT and token refresh
- Seed data script
- Initial migrations for all domain apps

## TODO

- Add automated tests for API behavior and checkout race conditions
- Strengthen race condition tests around checkout stock locking
- Add Redis caching to product list/detail endpoints
- Add batch report chunking for large order tables
- Add resource capacity controls such as checkout throttling or worker limits
- Add k6 stress tests
- Add benchmarking scripts and result documentation
- Add Nginx for load distribution across multiple Django containers
- Add database indexes after observing query patterns
- Add stricter production settings

## Parallel Programming Coverage Plan

- Race Condition Protection: checkout already locks product rows with `select_for_update()` inside `transaction.atomic()`.
- Resource Management: later add DRF throttling, Celery worker concurrency limits, and connection pool tuning.
- Queues: Celery is configured with Redis and placeholder order/report tasks.
- Batch Processing: daily sales report task is ready to evolve into chunk-based processing.
- Load Distribution: `/api/server-info/` returns `SERVER_NAME`; later Nginx can route across multiple `web` replicas.
- Redis Cache: settings include Redis cache; later product and report endpoints can cache expensive reads.
- Stress Testing: k6 will later simulate concurrent browse, cart, and checkout scenarios.
- Benchmarking: performance logs capture endpoint duration; later benchmark scripts can compare baseline vs optimized versions.

## Later Nginx Load Distribution

Nginx should be added after the base backend is stable. The intended setup is multiple Django `web` containers behind one Nginx reverse proxy. Each `web` container will use a different `SERVER_NAME`, and `/api/server-info/` will confirm request distribution.

This step is intentionally not implemented yet to keep the first project phase focused on a correct monolithic backend foundation.
