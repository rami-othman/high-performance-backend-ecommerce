# Task 9 Stress Test Summary

- Result: **PASSED**
- Total users: 100
- Total requests: 1003
- Successful users: 100
- Failed users: 0
- Successful checkouts: 100
- Failed checkouts: 0
- Requests per second: 151.9
- Average response time: 619.01 ms
- Min response time: 19.57 ms
- Max response time: 2840.57 ms
- P95 response time: 1905.39 ms
- Error rate: 0.0
- Server errors: 0
- Report operations passed: True

## Data Integrity

- Passed: True
- Negative stock: False
- Overselling: False
- Stock matches sales: True
- Orders match successful checkouts: True
- Payments match successful checkouts: True

## Status Codes

- `200`: 603
- `201`: 200
- `403`: 200

## Per-Operation Timing

- `add_product_to_cart`: count=100, errors=0, avg=729.12 ms, p95=2008.44 ms
- `checkout`: count=100, errors=0, avg=1000.44 ms, p95=2263.77 ms
- `create_admin_report_user_and_issue_jwt`: count=1, errors=0, avg=568.78 ms, p95=568.78 ms
- `create_test_user_and_issue_jwt`: count=100, errors=0, avg=598.01 ms, p95=691.16 ms
- `get_cached_product_detail_again`: count=100, errors=0, avg=408.9 ms, p95=1014.45 ms
- `get_daily_sales_batch_run_as_admin`: count=1, errors=0, avg=22.7 ms, p95=22.7 ms
- `get_daily_sales_report_as_admin`: count=1, errors=0, avg=27.97 ms, p95=27.97 ms
- `get_daily_sales_report_as_regular_user`: count=100, errors=0, avg=321.19 ms, p95=974.14 ms
- `get_order_history`: count=100, errors=0, avg=570.21 ms, p95=1682.88 ms
- `get_performance_capacity`: count=100, errors=0, avg=401.31 ms, p95=1228.13 ms
- `get_product_detail`: count=100, errors=0, avg=595.52 ms, p95=1750.4 ms
- `get_product_list`: count=100, errors=0, avg=880.81 ms, p95=2284.11 ms
- `update_cart_item_quantity`: count=100, errors=0, avg=696.92 ms, p95=1959.41 ms
