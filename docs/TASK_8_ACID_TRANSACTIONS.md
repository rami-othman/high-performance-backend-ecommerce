# Task 8 - ACID Transaction Integrity

## Goal

Task 8 proves that checkout is atomic. Order creation, order items, payment creation, product stock reduction, cart clearing, cache invalidation registration, and asynchronous task dispatch registration are coordinated by one database transaction.

## ACID in this project

ACID means:

- Atomicity: checkout either commits all required database changes or rolls them all back.
- Consistency: checkout leaves the database in a valid e-commerce state. A paid order has order items and a completed payment, stock is reduced by the sold quantity, and the cart is cleared only after the order is created.
- Isolation: checkout uses row-level locks so concurrent requests cannot read and update the same cart/product rows unsafely.
- Durability: after PostgreSQL commits, the order, payment, stock update, and cart clearing remain stored.

## Transaction boundary

The checkout transaction is in `orders/views.py`, inside `CheckoutView.run_checkout()`:

```python
with transaction.atomic():
    ...
```

Inside this transaction, checkout:

1. Locks the user's `Cart` row with `select_for_update()`.
2. Locks the cart's `CartItem` rows with `select_for_update()`.
3. Locks the selected `Product` rows with `select_for_update()` in deterministic `id` order.
4. Validates available stock.
5. Creates the `Order`.
6. Creates the `OrderItem` rows.
7. Reduces `Product.stock`.
8. Creates the `Payment`.
9. Deletes the cart items to clear the cart.
10. Registers post-commit cache invalidation.
11. Registers post-commit Celery task dispatch.

If an exception happens before the transaction commits, PostgreSQL rolls back every database write made inside the block.

## Post-commit work

Celery dispatch and cache invalidation are not executed directly inside the transaction. They are registered with:

```python
transaction.on_commit(...)
```

This matters because external side effects should not run for rolled-back orders. If checkout fails after an order/payment/stock/cart write, Django discards the registered `on_commit()` callbacks when the transaction rolls back. That prevents:

- invoice/notification tasks for an order that no longer exists
- cache invalidation for stock/report changes that did not commit

## Failure injection

Checkout supports a test-only failure hook:

```text
X-Debug-Fail-Checkout-After-Stock: 1
```

Equivalent query parameter:

```text
debug_fail_checkout_after_stock=1
```

The hook only works when `DEBUG=True` or `TESTING=True`. In production-like settings where both are false, the header is ignored.

When enabled, checkout raises an exception after stock has been reduced, payment and order rows have been created, the cart has been cleared, and `on_commit()` callbacks have been registered, but before the transaction commits. The proof verifies that all of those changes are rolled back and that post-commit callbacks do not run.

## Automated tests

The tests in `orders/tests.py` cover:

- successful checkout creates one order, one order item, one payment, reduces stock, clears the cart, and dispatches background tasks after commit
- injected failure rolls back order, order items, payment, stock, and cart clearing
- injected failure does not dispatch Celery tasks
- injected failure does not invalidate caches
- the debug failure header is ignored when `DEBUG=False` and `TESTING=False`
- concurrent checkout does not oversell shared stock

Run the focused tests:

```bash
python manage.py test orders.tests
```

## Proof script

Run the API server first. With Docker Compose:

```bash
docker compose up -d db redis web celery
```

Or run Django locally after PostgreSQL and Redis are available:

```bash
python manage.py runserver
```

Then run:

```bash
python scripts/acid_transaction_test.py --base-url http://127.0.0.1:8000
```

The script:

1. Creates an isolated success user, product, and cart.
2. Records initial stock/cart/order/payment counts.
3. Calls successful checkout through the API.
4. Verifies the committed state.
5. Creates a second isolated rollback user, product, and cart.
6. Calls checkout with `X-Debug-Fail-Checkout-After-Stock: 1`.
7. Verifies stock is unchanged, cart is unchanged, and no order/payment remains.
8. Saves the JSON result to:

```text
results/acid/task8_acid_transaction_latest.json
```

The JSON contains:

- `success_case`
- `rollback_case`
- `initial_state`
- `final_state`
- `result`

`result` is `PASSED` only when both the commit case and rollback case pass.
