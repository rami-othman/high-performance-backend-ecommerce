# Task 7 - Redis Distributed Locks

## 1. Requirement

Use Redis distributed locks outside database row locks to coordinate work across multiple Django web and worker instances.

## 2. Why Database Locks Are Not Enough

Database row locks are still required for stock integrity during checkout because they protect product rows while quantities are updated.

They do not cover every concurrency problem:

- Duplicate checkout submission should be rejected before multiple requests enter expensive checkout work.
- Two Celery workers can start the same daily report date at the same time before either one updates final report rows.
- Many web workers can see an expired cache key at the same time and all query PostgreSQL to rebuild the same response.

Redis distributed locks solve these cross-process coordination cases because every Django and Celery instance shares the same Redis lock namespace.

## 3. Reusable Lock Utility

The shared implementation lives in `performance/distributed_locks.py`.

It uses `redis-py` and connects through:

```python
CACHE_URL or REDIS_URL
```

The main API is:

```python
with redis_distributed_lock(name, timeout=10, blocking_timeout=0) as lock:
    if lock.acquired:
        ...
```

The utility:

- Normalizes all keys to the `lock:` prefix.
- Supports `timeout` and `blocking_timeout`.
- Releases only if the lock was acquired.
- Ignores release errors for locks that expired before release.
- Reports normal contention status as `ACQUIRED`, `WAITED`, or `BUSY`.
- Cache rebuild callers never rebuild data unless they acquire the lock.

## 4. Where Locks Are Used

| Scenario | File | Lock key |
| --- | --- | --- |
| Checkout duplicate submission | `orders/views.py` | `lock:checkout:user:<user_id>` |
| Daily sales same-date processing | `reports/tasks.py` | `lock:daily-sales:<YYYY-MM-DD>` |
| Product list cache rebuild | `products/views.py` | `lock:cache-rebuild:products:list` |
| Product detail cache rebuild | `products/views.py` | `lock:cache-rebuild:products:detail:<id>` |
| Daily sales report list cache rebuild | `reports/views.py` | `lock:cache-rebuild:reports:daily-sales:list` |
| Daily sales batch-run detail cache rebuild | `reports/views.py` | `lock:cache-rebuild:reports:daily-sales:batch-run:<id>` |

## 5. Timeout Strategy

- Checkout duplicate lock timeout: 15 seconds.
- Daily sales report lock timeout: 300 seconds by default through `DAILY_SALES_DISTRIBUTED_LOCK_TIMEOUT_SECONDS`.
- Cache rebuild lock timeout: 10 seconds.
- Checkout and daily sales use `blocking_timeout=0` to fail fast.
- Cache rebuilds use `blocking_timeout=2` so requests can wait briefly for another process to rebuild the cache.

Lock timeouts are intentionally longer than normal expected work but short enough to recover if a process exits before releasing.

## 6. Busy Behavior

Checkout:

```json
{
  "code": "checkout_lock_busy",
  "detail": "Checkout is already running for this user."
}
```

The response status is `429 Too Many Requests`.

Daily sales report task:

```json
{
  "status": "skipped",
  "reason": "distributed_lock_busy"
}
```

The related `DailySalesBatchRun` is marked as `failure` with an explanatory error message, because it did not process.

Cache rebuild:

- Cache hit: returns `X-Cache: HIT`.
- Cache miss and lock acquired: returns `X-Cache: MISS` and `X-Lock: ACQUIRED`.
- Cache miss while another worker rebuilds: waits briefly, checks cache again, and returns `X-Cache: HIT` with `X-Lock: WAITED` if the other worker populated the cache.
- Cache miss when the rebuild lock is still busy and cache remains empty: returns `503 Service Unavailable` and does not query PostgreSQL.

Busy cache rebuild response:

```json
{
  "code": "cache_rebuild_lock_busy",
  "detail": "Cache rebuild is already running. Try again shortly."
}
```

## 7. Proof Script

Run Redis/PostgreSQL, then execute:

```bash
python scripts/distributed_lock_test.py
```

Docker:

```bash
docker compose up --build
docker compose exec web python scripts/distributed_lock_test.py
```

The script:

1. Starts concurrent threads competing for one Redis lock.
2. Simulates duplicate checkout lock acquisition for the same user.
3. Holds a same-date daily sales lock and runs the Celery task eagerly to prove it returns `skipped`.
4. Saves proof JSON under `results/locks/`.

Latest output:

```text
results/locks/task7_distributed_lock_latest.json
```

The JSON includes:

- `total_attempts`
- `acquired_count`
- `blocked_count`
- `lock_keys_used`
- `result`

Expected result:

```text
Task 7 - Redis Distributed Lock Proof

Total attempts: 12
Acquired count: 3
Blocked count: 9
Result: PASSED
```
