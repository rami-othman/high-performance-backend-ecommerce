from django.core.cache import cache


X_CACHE_HEADER = "X-Cache"
X_LOCK_HEADER = "X-Lock"
CACHE_HIT = "HIT"
CACHE_MISS = "MISS"

PRODUCT_LIST_CACHE_KEY = "products:list:v1"
PRODUCT_DETAIL_CACHE_KEY_PREFIX = "products:detail:v1"
DAILY_SALES_REPORTS_LIST_CACHE_KEY = "reports:daily-sales:list:v1"
DAILY_SALES_BATCH_RUN_DETAIL_CACHE_KEY_PREFIX = "reports:daily-sales:batch-run:v1"
DAILY_SALES_BATCH_RUN_CACHE_INDEX_KEY = "reports:daily-sales:cached-batch-run-ids:v1"

PRODUCT_LIST_CACHE_TIMEOUT_SECONDS = 60
PRODUCT_DETAIL_CACHE_TIMEOUT_SECONDS = 120
DAILY_SALES_REPORTS_LIST_CACHE_TIMEOUT_SECONDS = 60
DAILY_SALES_BATCH_RUN_DETAIL_CACHE_TIMEOUT_SECONDS = 30


def product_detail_cache_key(product_id):
    return f"{PRODUCT_DETAIL_CACHE_KEY_PREFIX}:{product_id}"


def daily_sales_batch_run_detail_cache_key(batch_run_id):
    return f"{DAILY_SALES_BATCH_RUN_DETAIL_CACHE_KEY_PREFIX}:{batch_run_id}"


def set_cache_header(response, cache_status):
    response[X_CACHE_HEADER] = cache_status
    return response


def set_lock_header(response, lock_status):
    response[X_LOCK_HEADER] = lock_status
    return response


def set_cache_and_lock_headers(response, cache_status, lock_status):
    set_cache_header(response, cache_status)
    set_lock_header(response, lock_status)
    return response


def remember_daily_sales_batch_run_cache(batch_run_id):
    batch_run_ids = set(cache.get(DAILY_SALES_BATCH_RUN_CACHE_INDEX_KEY) or [])
    batch_run_ids.add(int(batch_run_id))
    cache.set(DAILY_SALES_BATCH_RUN_CACHE_INDEX_KEY, batch_run_ids, timeout=None)


def invalidate_product_caches(product_ids):
    keys = [PRODUCT_LIST_CACHE_KEY]
    keys.extend(product_detail_cache_key(product_id) for product_id in product_ids)
    cache.delete_many(keys)


def invalidate_daily_sales_report_caches():
    batch_run_ids = cache.get(DAILY_SALES_BATCH_RUN_CACHE_INDEX_KEY) or set()
    keys = [DAILY_SALES_REPORTS_LIST_CACHE_KEY]
    keys.extend(daily_sales_batch_run_detail_cache_key(batch_run_id) for batch_run_id in batch_run_ids)
    cache.delete_many(keys)
    cache.delete(DAILY_SALES_BATCH_RUN_CACHE_INDEX_KEY)


def invalidate_checkout_related_caches(product_ids):
    invalidate_product_caches(product_ids)
    invalidate_daily_sales_report_caches()
