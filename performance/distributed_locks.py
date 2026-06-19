import os
import time
from dataclasses import dataclass

import redis
from django.conf import settings
from redis.exceptions import LockError, RedisError


LOCK_KEY_PREFIX = "lock:"
LOCK_ACQUIRED = "ACQUIRED"
LOCK_WAITED = "WAITED"
LOCK_BYPASSED = "BYPASSED"
LOCK_BUSY = "BUSY"

DEFAULT_LOCK_TIMEOUT_SECONDS = 10
DEFAULT_BLOCKING_TIMEOUT_SECONDS = 0
WAITED_THRESHOLD_SECONDS = 0.01


def get_lock_redis_url():
    return getattr(settings, "CACHE_URL", None) or os.getenv("CACHE_URL") or settings.REDIS_URL


def get_lock_redis_client():
    return redis.Redis.from_url(get_lock_redis_url())


def normalize_lock_key(name):
    name = str(name)
    if name.startswith(LOCK_KEY_PREFIX):
        return name
    return f"{LOCK_KEY_PREFIX}{name}"


def checkout_user_lock_key(user_id):
    return normalize_lock_key(f"checkout:user:{user_id}")


def daily_sales_report_lock_key(report_date):
    return normalize_lock_key(f"daily-sales:{report_date}")


def product_list_cache_rebuild_lock_key():
    return normalize_lock_key("cache-rebuild:products:list")


def product_detail_cache_rebuild_lock_key(product_id):
    return normalize_lock_key(f"cache-rebuild:products:detail:{product_id}")


def daily_sales_reports_list_cache_rebuild_lock_key():
    return normalize_lock_key("cache-rebuild:reports:daily-sales:list")


def daily_sales_batch_run_detail_cache_rebuild_lock_key(batch_run_id):
    return normalize_lock_key(f"cache-rebuild:reports:daily-sales:batch-run:{batch_run_id}")


@dataclass
class RedisDistributedLock:
    name: str
    timeout: int = DEFAULT_LOCK_TIMEOUT_SECONDS
    blocking_timeout: float = DEFAULT_BLOCKING_TIMEOUT_SECONDS
    client: object = None

    def __post_init__(self):
        self.key = normalize_lock_key(self.name)
        self.acquired = False
        self.status = LOCK_BUSY
        self.error = None
        self._lock = None

    def __enter__(self):
        client = self.client or get_lock_redis_client()
        should_block = self.blocking_timeout is None or self.blocking_timeout > 0
        started_at = time.monotonic()

        try:
            self._lock = client.lock(
                self.key,
                timeout=self.timeout,
                blocking_timeout=self.blocking_timeout,
            )
            self.acquired = self._lock.acquire(blocking=should_block, blocking_timeout=self.blocking_timeout)
            if self.acquired:
                waited_seconds = time.monotonic() - started_at
                self.status = LOCK_WAITED if waited_seconds >= WAITED_THRESHOLD_SECONDS else LOCK_ACQUIRED
            else:
                self.status = LOCK_BUSY
        except RedisError as exc:
            self.acquired = False
            self.status = LOCK_BYPASSED
            self.error = str(exc)

        return self

    def __exit__(self, exc_type, exc, traceback):
        if self.acquired and self._lock is not None:
            try:
                self._lock.release()
            except (LockError, RedisError):
                pass
        return False


def redis_distributed_lock(
    name,
    timeout=DEFAULT_LOCK_TIMEOUT_SECONDS,
    blocking_timeout=DEFAULT_BLOCKING_TIMEOUT_SECONDS,
    client=None,
):
    return RedisDistributedLock(
        name=name,
        timeout=timeout,
        blocking_timeout=blocking_timeout,
        client=client,
    )
