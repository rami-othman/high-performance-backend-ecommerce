from rest_framework import status, viewsets
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from django.core.cache import cache

from performance.distributed_locks import (
    LOCK_WAITED,
    product_detail_cache_rebuild_lock_key,
    product_list_cache_rebuild_lock_key,
    redis_distributed_lock,
)
from .cache_utils import (
    CACHE_HIT,
    CACHE_MISS,
    PRODUCT_DETAIL_CACHE_TIMEOUT_SECONDS,
    PRODUCT_LIST_CACHE_KEY,
    PRODUCT_LIST_CACHE_TIMEOUT_SECONDS,
    product_detail_cache_key,
    set_cache_and_lock_headers,
    set_cache_header,
)
from .models import Product
from .serializers import ProductSerializer


def cache_rebuild_busy_response(cache_key):
    return Response(
        {
            "code": "cache_rebuild_lock_busy",
            "detail": "Cache rebuild is already running. Try again shortly.",
            "cache_key": cache_key,
        },
        status=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


class ProductViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Product.objects.all()
    serializer_class = ProductSerializer
    permission_classes = [AllowAny]

    # =========================
    # LIST - Products caching
    # =========================
    def list(self, request, *args, **kwargs):
        cached_data = cache.get(PRODUCT_LIST_CACHE_KEY)
        if cached_data is not None:
            return set_cache_header(Response(cached_data), CACHE_HIT)

        with redis_distributed_lock(
            product_list_cache_rebuild_lock_key(),
            timeout=10,
            blocking_timeout=2,
        ) as rebuild_lock:
            cached_data = cache.get(PRODUCT_LIST_CACHE_KEY)
            if cached_data is not None:
                lock_status = LOCK_WAITED if not rebuild_lock.acquired else rebuild_lock.status
                return set_cache_and_lock_headers(Response(cached_data), CACHE_HIT, lock_status)

            if not rebuild_lock.acquired:
                return cache_rebuild_busy_response(PRODUCT_LIST_CACHE_KEY)

            response = super().list(request, *args, **kwargs)
            cache.set(PRODUCT_LIST_CACHE_KEY, response.data, timeout=PRODUCT_LIST_CACHE_TIMEOUT_SECONDS)
            return set_cache_and_lock_headers(response, CACHE_MISS, rebuild_lock.status)

    # =========================
    # RETRIEVE - Product caching
    # =========================
    def retrieve(self, request, *args, **kwargs):
        pk = kwargs.get("pk")
        cache_key = product_detail_cache_key(pk)

        cached_data = cache.get(cache_key)
        if cached_data is not None:
            return set_cache_header(Response(cached_data), CACHE_HIT)

        with redis_distributed_lock(
            product_detail_cache_rebuild_lock_key(pk),
            timeout=10,
            blocking_timeout=2,
        ) as rebuild_lock:
            cached_data = cache.get(cache_key)
            if cached_data is not None:
                lock_status = LOCK_WAITED if not rebuild_lock.acquired else rebuild_lock.status
                return set_cache_and_lock_headers(Response(cached_data), CACHE_HIT, lock_status)

            if not rebuild_lock.acquired:
                return cache_rebuild_busy_response(cache_key)

            response = super().retrieve(request, *args, **kwargs)
            cache.set(cache_key, response.data, timeout=PRODUCT_DETAIL_CACHE_TIMEOUT_SECONDS)
            return set_cache_and_lock_headers(response, CACHE_MISS, rebuild_lock.status)
