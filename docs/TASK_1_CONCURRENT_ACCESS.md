# Task 1 - Concurrent Access & Data Integrity

## Requirement Summary

The system must allow multiple users to modify the same shared resource without data conflicts. For this project, the most important shared resource is product inventory during checkout. The project must also prove that the race condition problem is handled.

## Shared Resource

The shared resource is `Product.stock`.

Many users can try to buy the same product at the same time. If stock updates are not synchronized, two requests can read the same stock value and both create orders, causing incorrect inventory or overselling.

## The Race Condition Problem

Simple example:

1. Product stock is `1`.
2. User A starts checkout and reads stock as `1`.
3. User B starts checkout at the same time and also reads stock as `1`.
4. Both users believe stock is available.
5. Both orders are created.
6. The system has sold `2` units even though only `1` unit existed.

This is a race condition because the result depends on the timing of concurrent requests.

## Chosen Solution

The project uses pessimistic locking for checkout:

- `transaction.atomic()` creates one database transaction for the checkout read/write flow.
- `select_for_update()` locks database rows that are being checked and modified.
- PostgreSQL row-level locks make concurrent transactions wait before modifying the same product stock.

## Why Pessimistic Locking

Pessimistic locking was chosen because it is easy to explain, provides strong consistency, and fits checkout and inventory use cases. During checkout, correctness is more important than allowing every request to proceed immediately.

With row-level locks, two transactions cannot modify the same `Product.stock` at the same time. One transaction locks the product row, completes validation and stock reduction, then commits. The next transaction reads the updated stock after the first transaction finishes.

## Checkout Synchronization Flow

The checkout endpoint is `POST /api/orders/checkout/` in `orders/views.py`.

The flow is:

1. Start `transaction.atomic()`.
2. Lock the authenticated user's cart using `select_for_update()`.
3. Read cart items only after the cart lock is held.
4. Return `400` if the cart is empty.
5. Collect product IDs from cart items.
6. Lock all required product rows using `select_for_update()`.
7. Lock products in deterministic order using `order_by("id")`.
8. Validate all stock before creating the order.
9. Create the order only after validation passes.
10. Create order item rows.
11. Reduce product stock while product rows are locked.
12. Increment `Product.version`.
13. Create the payment record.
14. Clear cart items.
15. Dispatch invoice and notification Celery tasks with `transaction.on_commit()`.

## Why Lock The Cart

The cart lock prevents the same user from submitting duplicate checkout requests for the same cart at the same time.

If two checkout requests from the same user arrive together, the first request locks the cart, creates the order, and clears the cart. The second request waits for the cart lock, then rereads the cart after the first transaction commits. It sees an empty cart and returns `400`.

## Why Lock Products In Deterministic Order

Products are locked using `order_by("id")`.

This reduces deadlock risk when different users buy multiple products in different cart orders. If every transaction locks products in the same order, transactions are less likely to wait on each other in a circular pattern.

## Proof Script

The proof script is:

```text
scripts/race_condition_test.py
```

The script uses Django ORM only for setup and final verification. The actual checkout requests are real HTTP requests to the running API.

Default scenario:

- Initial stock: `5`
- Concurrent users: `20`
- Quantity per user: `1`
- Expected successful checkouts: `5`
- Expected failed checkouts: `15`
- Expected final stock: `0`
- Stock must never become negative.
- Total sold quantity must never exceed initial stock.

The script creates test users named `race_user_001`, `race_user_002`, and so on. It creates one cart item for each test user, then starts all checkout requests together using a thread barrier.

The script saves results to:

```text
results/race_condition_task1_latest.json
results/race_condition_task1_YYYYMMDD_HHMMSS.json
```

## How To Run

Start the Django server first:

```bash
python manage.py runserver
```

Then run the proof script:

```bash
python scripts/race_condition_test.py
```

Optional arguments:

```bash
python scripts/race_condition_test.py --users 20 --stock 5 --quantity 1
```

The API base URL can be changed with either an environment variable or a CLI argument:

```bash
API_BASE_URL=http://127.0.0.1:8000 python scripts/race_condition_test.py
python scripts/race_condition_test.py --base-url http://127.0.0.1:8000
```

Docker example:

```bash
docker compose exec web python scripts/race_condition_test.py --base-url http://localhost:8000
```

If Docker networking requires a different host, use one of these:

```bash
API_BASE_URL=http://127.0.0.1:8000 python scripts/race_condition_test.py
API_BASE_URL=http://web:8000 python scripts/race_condition_test.py
```

## Expected Output

Sample output:

```text
Task 1 - Race Condition Proof

Initial stock: 5
Concurrent users: 20
Quantity per user: 1

Successful checkouts: 5
Failed checkouts: 15
Final stock: 0
Total sold quantity: 5
Negative stock: No
Overselling: No

Result: PASSED
```

## Final Conclusion

The system protects `Product.stock` from race conditions during checkout using database transactions and PostgreSQL row-level locks. The proof script demonstrates that concurrent users cannot oversell inventory: only the available stock can be sold, final stock does not become negative, and failed checkout requests receive clear API failures after stock is exhausted.
