# Task 9 - 100 User Stress Testing

## Goal

Task 9 proves that the backend can handle at least 100 concurrent e-commerce users without crashing, overselling product stock, or losing checkout data.

The old root `stress_test.py` only exercised product listing. It now delegates to `scripts/stress_test_100_users.py`, which runs a full shopping flow.

## Operations tested

Each simulated user receives an isolated test account and JWT token, then runs this flow:

1. Create unique stress-test user.
2. Issue a JWT token for that user.
3. `GET /api/products/`
4. `GET /api/products/{id}/`
5. `POST /api/cart/items/`
6. `PATCH /api/cart/items/{item_id}/`
7. `POST /api/orders/checkout/`
8. `GET /api/orders/`
9. `GET /api/products/{id}/` again to hit the cached product detail endpoint.
10. `GET /api/performance/capacity/`
11. `GET /api/reports/daily-sales/` as a regular user.

The performance and report endpoints are admin-only. Regular stress users are expected to receive either `200` if allowed or `403` if denied; both are recorded, and `403` is not treated as a system failure for those optional regular-user endpoint checks.

The script also creates one isolated admin stress user after creating the regular users. That admin user must successfully call:

- `GET /api/reports/daily-sales/`
- `GET /api/reports/daily-sales/batch-runs/{id}/` when at least one batch run exists

The admin report requests are included in the same timing, status-code, and per-operation metrics. Unlike regular-user `403` responses, an admin report failure makes the stress proof fail.

## How users are simulated

The script uses Python `ThreadPoolExecutor` with `max_workers` equal to the configured user count. The default is 100 users:

```bash
python scripts/stress_test_100_users.py
```

Before the concurrent phase, the script:

- deletes previous Task 9 stress users and products
- creates 10 isolated stress products by default
- gives each product enough stock for the planned load
- creates 100 isolated stress users and issues JWT tokens
- creates one isolated admin stress user for report endpoint coverage
- warms product list/detail caches to avoid measuring first-request cache rebuild contention

User creation and token issuance are measured in the result as setup operations. They are done before the concurrent HTTP phase so the stress proof does not get dominated by the project's auth throttle or local script database connections. During the concurrent phase, each worker uses a unique user and buys quantity `1` by default.

## Data integrity verification

After all workers finish, the script queries the database and verifies:

- no product has negative stock
- no product sold more units than its initial stock
- final stock equals initial stock minus sold quantity for each stress product
- paid order count equals successful checkout count
- completed payment count equals successful checkout count

The script fails the proof if these integrity checks fail.

## Metrics collected

The JSON result includes:

- total users
- total requests/operations recorded
- successful users
- failed users
- successful checkouts
- failed checkouts
- average response time
- min response time
- max response time
- p95 response time
- requests per second
- error rate
- status code distribution
- per-operation timing summary
- failed requests with user number, operation, status code, and error reason
- per-product stock/sales integrity details
- admin report operation result details

## Output files

The script writes:

```text
results/stress/task9_stress_100_users_latest.json
results/stress/task9_stress_100_users_summary.md
```

It also writes a timestamped JSON file next to the latest file.

## Run locally

Start PostgreSQL and Redis, then run Django:

```bash
docker compose up -d db redis
python manage.py migrate
python manage.py runserver
```

In another terminal:

```bash
python scripts/stress_test_100_users.py --base-url http://127.0.0.1:8000
```

The root compatibility command also works:

```bash
python stress_test.py --base-url http://127.0.0.1:8000
```

## Run with Docker

Start the full stack:

```bash
docker compose up -d --build
```

Run the script from the host through HAProxy:

```bash
python scripts/stress_test_100_users.py --base-url http://127.0.0.1:8000
```

Or run it from a web container:

```bash
docker compose exec web python scripts/stress_test_100_users.py --base-url http://load_balancer
```

## Checkout capacity note

The project has a Redis-backed checkout capacity limiter from Task 2. For an isolated 100-user stress proof, the script sends the existing DEBUG-only capacity override header:

```text
X-Race-Condition-Test-Capacity-Limit: max(150, user_count)
```

This allows the stress test to evaluate checkout transaction correctness under 100 concurrent users instead of proving the capacity limiter rejects excess requests. Production-like settings ignore this header unless `DEBUG=True` or the dedicated test override setting is enabled.

If the override is ignored, some checkouts may return `429` from the capacity limiter. Those failures are recorded in the output, and the summary result will be `FAILED` because the default proof expects all 100 users to complete checkout successfully.

## Interpreting the result

`PASSED` means:

- at least 100 users were simulated
- every user completed the flow
- every checkout succeeded
- admin report endpoint checks succeeded
- no server-side 5xx/no-response failures occurred
- stock, orders, and payments remained consistent

`FAILED` means at least one of those checks failed. Inspect:

- `summary.failed_request_count`
- `summary.status_code_distribution`
- `failed_requests`
- `data_integrity.products`
- per-operation timing under `timing.per_operation`

Capacity rejections show up as `429`. Cache rebuild contention can show up as `503` from product/report cache endpoints. Database or application failures show up as `5xx` or `no_response`.
