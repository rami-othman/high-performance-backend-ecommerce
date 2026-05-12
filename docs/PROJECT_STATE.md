# Project State: High-Performance E-Commerce Backend Engine

This file is intended to be pasted into a new ChatGPT or Codex chat so the project can continue with context.

## Project Summary

The project is a Parallel Programming university project named **High-Performance E-Commerce Backend Engine**. It is a clean monolithic Django backend for an e-commerce system. The current goal is to finish the base foundation first, not full optimization.

The future demonstrations will cover concurrent access and data integrity, resource management, asynchronous queues, batch processing, load distribution, Redis caching, concurrency control and locking, ACID transactions, stress testing, and benchmarking.

## Chosen Stack

- Python 3.11
- Django
- Django REST Framework
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

## File Structure

```text
high_performance_ecommerce/
|-- config/
|   |-- __init__.py
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
|   |-- middleware.py
|   |-- models.py
|   |-- serializers.py
|   |-- system_urls.py
|   |-- urls.py
|   `-- views.py
|-- templates/
|   |-- base.html
|   |-- home.html
|   |-- products.html
|   |-- cart.html
|   |-- orders.html
|   `-- dashboard.html
|-- docs/
|   `-- PROJECT_STATE.md
|-- scripts/
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
- `GET /api/health/`
- `GET /api/server-info/`

### API Documentation

- `GET /api/schema/`
- `GET /api/docs/`

### Simple UI

- `/`
- `/products-ui/`
- `/cart-ui/`
- `/orders-ui/`
- `/dashboard/`

## Current Progress

The base Django project has been scaffolded. The domain apps, models, serializers, API views, URL routing, middleware, Celery setup, Docker Compose setup, templates, README, environment example, seed script, and initial migrations are in place.

Checkout currently:

1. Reads the authenticated user's cart items.
2. Enters `transaction.atomic()`.
3. Locks selected product rows with `select_for_update()`.
4. Validates stock.
5. Creates an order.
6. Creates order items.
7. Reduces product stock and increments product version.
8. Creates a completed payment record.
9. Clears the cart.
10. Dispatches placeholder Celery tasks after the transaction succeeds.

## Next Tasks

1. Install dependencies in a Conda environment.
2. Create `.env` from `.env.example`.
3. Start PostgreSQL and Redis locally or use Docker Compose.
4. Run `python manage.py migrate`.
5. Create a superuser.
6. Seed sample products.
7. Test Swagger endpoints manually.
8. Add automated API tests.
9. Add stress tests with k6.
10. Add Redis caching to product endpoints.
11. Add Nginx and multiple web replicas for load balancing.
12. Add benchmarking scripts and write benchmark reports.

## Known Decisions

- Use Django default `auth.User`.
- Use monolithic Django architecture.
- Use PostgreSQL as the main relational database.
- Use Redis for cache and Celery broker/result backend.
- Use Celery for async jobs.
- Use k6 later for stress testing.
- Use Nginx later for load balancing.
- Do not add a custom user model.
- Do not create microservices.
- Keep the first phase focused on the base foundation, not full optimization.

## Important Notes

The project is intentionally simple at this stage. The checkout path includes the main transaction and locking points needed for later race-condition testing. Performance logging is basic and database-backed so benchmarking can start early, but it may later need buffering or sampling to reduce overhead under heavy load.
