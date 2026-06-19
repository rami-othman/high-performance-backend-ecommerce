# Task 6 - Redis/Django Caching

## 1. Requirement

Use Redis through Django's cache framework in multiple places to reduce repeated database work and improve response time.

## 2. Where Caching Is Used

- `GET /api/products/`
- `GET /api/products/<id>/`
- `GET /api/reports/daily-sales/`
- `GET /api/reports/daily-sales/batch-runs/<id>/`

Each cached response includes an `X-Cache` response header:

- `X-Cache: MISS` means Django queried the database and then stored the serialized response.
- `X-Cache: HIT` means Django returned the serialized response directly from cache.

## 3. Why Redis Helps

Product catalog and report endpoints are read-heavy compared with writes. Without caching, repeated requests deserialize the same rows and run the same database queries.

Redis stores the already serialized response data in memory, so repeated requests avoid PostgreSQL reads and serializer work until the cache expires or is invalidated.

The project configures Django cache in `config/settings.py`:

```python
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": os.getenv("CACHE_URL", REDIS_URL),
    }
}
```

## 4. Cache Keys

Cache key helpers and constants live in `products/cache_utils.py`.

| Purpose | Key |
| --- | --- |
| Product list | `products:list:v1` |
| Product detail | `products:detail:v1:<product_id>` |
| Daily sales report list | `reports:daily-sales:list:v1` |
| Daily sales batch run detail | `reports:daily-sales:batch-run:v1:<batch_run_id>` |
| Cached batch-run detail index | `reports:daily-sales:cached-batch-run-ids:v1` |

Timeouts are also centralized in `products/cache_utils.py`:

- Product list: 60 seconds
- Product detail: 120 seconds
- Daily sales report list: 60 seconds
- Daily sales batch run detail: 30 seconds

Batch-run detail uses a shorter timeout because those rows can change while a Celery job is processing.

## 5. Invalidation Strategy

Checkout changes product stock and creates sales data, so `orders/views.py` invalidates caches after the database transaction commits:

- Delete the product list cache.
- Delete each changed product detail cache.
- Delete the daily sales report list cache.
- Delete cached daily sales batch-run details recorded in the batch-run cache index.

The invalidation is registered with `transaction.on_commit(...)`, so cache entries are not deleted if checkout rolls back.

`reports/tasks.py` also invalidates report caches when daily sales processing finishes or fails, because `DailySalesReport` and `DailySalesBatchRun` rows are updated by the Celery task.

## 6. Proof Script

Run the API stack, then execute:

```bash
python scripts/cache_test.py
```

Docker:

```bash
docker compose up --build
docker compose exec web python scripts/cache_test.py
```

The script:

1. Creates isolated demo product, report, batch-run, and admin user data.
2. Clears only the Task 6 cache keys.
3. Calls each cached endpoint twice.
4. Records status code, `X-Cache`, response time, and JSON body.
5. Saves output under `results/cache/`.

Latest output:

```text
results/cache/cache_task6_latest.json
```

Expected proof:

```text
Task 6 - Redis/Django Cache Proof

Endpoints checked: 4
MISS then HIT headers: 4/4
Second request faster or equal: 4/4
Result: PASSED
```

Small local timing differences can be noisy, so the main proof is the `MISS` then `HIT` headers. The JSON result also records timing deltas for response-time comparison.
