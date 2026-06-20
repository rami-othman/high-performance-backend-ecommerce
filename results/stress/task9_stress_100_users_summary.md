# Task 9 Stress Test Summary

- Result: **PASSED**
- Total users: 100
- Total requests: 1003
- Successful users: 100
- Failed users: 0
- Successful checkouts: 100
- Failed checkouts: 0
- Requests per second: 224.71
- Average response time: 379.19 ms
- Min response time: 15.14 ms
- Max response time: 1671.69 ms
- P95 response time: 1167.46 ms
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

- `add_product_to_cart`: count=100, errors=0, avg=546.72 ms, p95=1445.27 ms
- `checkout`: count=100, errors=0, avg=629.93 ms, p95=1564.0 ms
- `create_admin_report_user_and_issue_jwt`: count=1, errors=0, avg=175.28 ms, p95=175.28 ms
- `create_test_user_and_issue_jwt`: count=100, errors=0, avg=205.2 ms, p95=274.86 ms
- `get_cached_product_detail_again`: count=100, errors=0, avg=373.01 ms, p95=1085.52 ms
- `get_daily_sales_batch_run_as_admin`: count=1, errors=0, avg=47.17 ms, p95=47.17 ms
- `get_daily_sales_report_as_admin`: count=1, errors=0, avg=44.29 ms, p95=44.29 ms
- `get_daily_sales_report_as_regular_user`: count=100, errors=0, avg=187.95 ms, p95=887.59 ms
- `get_order_history`: count=100, errors=0, avg=451.39 ms, p95=1214.53 ms
- `get_performance_capacity`: count=100, errors=0, avg=243.3 ms, p95=1026.2 ms
- `get_product_detail`: count=100, errors=0, avg=360.91 ms, p95=659.12 ms
- `get_product_list`: count=100, errors=0, avg=239.71 ms, p95=498.55 ms
- `update_cart_item_quantity`: count=100, errors=0, avg=562.5 ms, p95=1508.34 ms
