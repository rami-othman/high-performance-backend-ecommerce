from dataclasses import dataclass

import redis
from django.conf import settings


class CheckoutCapacityUnavailable(Exception):
    pass


def get_redis_client():
    return redis.Redis.from_url(settings.REDIS_URL, decode_responses=False)


def get_max_key(key=None):
    active_key = key or settings.CHECKOUT_CAPACITY_KEY
    if active_key.endswith(":active"):
        return active_key[: -len(":active")] + ":max_observed"
    return f"{active_key}:max_observed"


def to_int(value):
    if value in (None, b"", ""):
        return 0
    return int(value)


@dataclass
class CheckoutCapacityLimiter:
    redis_client: object = None
    key: str = None
    limit: int = None
    ttl_seconds: int = None

    def __post_init__(self):
        self.redis_client = self.redis_client or get_redis_client()
        self.key = self.key or settings.CHECKOUT_CAPACITY_KEY
        self.limit = self.limit or settings.CHECKOUT_MAX_CONCURRENT_REQUESTS
        self.ttl_seconds = self.ttl_seconds or settings.CHECKOUT_CAPACITY_TTL_SECONDS
        self.max_key = get_max_key(self.key)
        self.acquired = False
        self.active_count = 0

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, traceback):
        try:
            self.release()
        except CheckoutCapacityUnavailable:
            # If Redis fails during release after checkout work has completed,
            # do not turn a successful checkout into a misleading 503 response.
            # The counter has a TTL, so it will expire instead of leaking forever.
            pass
        return False

    def acquire(self):
        try:
            # Task 2 capacity control: Redis INCR is atomic, so all Django
            # workers share the same active checkout counter.
            self.active_count = int(self.redis_client.incr(self.key))
            self.redis_client.expire(self.key, self.ttl_seconds)

            if self.active_count > self.limit:
                self.redis_client.decr(self.key)
                self.acquired = False
                return False

            self.acquired = True
            update_max_observed(self.redis_client, self.max_key, self.active_count)
            return True
        except redis.RedisError as exc:
            raise CheckoutCapacityUnavailable("Redis checkout capacity limiter is unavailable.") from exc

    def release(self):
        if not self.acquired:
            return

        try:
            # Always release the slot. If a counter ever drops below zero because
            # of manual Redis changes, clamp it back to zero for safer metrics.
            active_count = int(self.redis_client.decr(self.key))
            if active_count < 0:
                self.redis_client.set(self.key, 0)
            else:
                self.redis_client.expire(self.key, self.ttl_seconds)
        except redis.RedisError as exc:
            raise CheckoutCapacityUnavailable("Redis checkout capacity limiter release failed.") from exc
        finally:
            self.acquired = False


def update_max_observed(redis_client, max_key, active_count):
    try:
        script = """
        local current = tonumber(ARGV[1])
        local observed = tonumber(redis.call('GET', KEYS[1]) or '0')
        if current > observed then
            redis.call('SET', KEYS[1], current)
        end
        return 1
        """
        redis_client.eval(script, 1, max_key, active_count)
    except AttributeError:
        observed = to_int(redis_client.get(max_key))
        if active_count > observed:
            redis_client.set(max_key, active_count)
    except redis.RedisError as exc:
        raise CheckoutCapacityUnavailable("Redis checkout capacity metrics are unavailable.") from exc


def reset_checkout_capacity_metrics(redis_client=None, key=None):
    client = redis_client or get_redis_client()
    active_key = key or settings.CHECKOUT_CAPACITY_KEY
    try:
        client.delete(active_key, get_max_key(active_key))
    except redis.RedisError as exc:
        raise CheckoutCapacityUnavailable("Redis checkout capacity metrics could not be reset.") from exc


def get_checkout_capacity_metrics(redis_client=None, key=None, limit=None):
    client = redis_client or get_redis_client()
    active_key = key or settings.CHECKOUT_CAPACITY_KEY
    configured_limit = limit or settings.CHECKOUT_MAX_CONCURRENT_REQUESTS
    try:
        active_count = to_int(client.get(active_key))
        if active_count < 0:
            client.set(active_key, 0)
            active_count = 0
        return {
            "checkout_limit": configured_limit,
            "active_checkouts": active_count,
            "max_observed_active_checkouts": to_int(client.get(get_max_key(active_key))),
        }
    except redis.RedisError as exc:
        raise CheckoutCapacityUnavailable("Redis checkout capacity metrics are unavailable.") from exc
