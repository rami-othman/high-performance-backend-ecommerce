from rest_framework import viewsets
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from django.core.cache import cache

from .cache_utils import (
    CACHE_HIT,
    CACHE_MISS,
    PRODUCT_DETAIL_CACHE_TIMEOUT_SECONDS,
    PRODUCT_LIST_CACHE_KEY,
    PRODUCT_LIST_CACHE_TIMEOUT_SECONDS,
    product_detail_cache_key,
    set_cache_header,
)
from .models import Product
from .serializers import ProductSerializer


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

        response = super().list(request, *args, **kwargs)

        cache.set(PRODUCT_LIST_CACHE_KEY, response.data, timeout=PRODUCT_LIST_CACHE_TIMEOUT_SECONDS)
        return set_cache_header(response, CACHE_MISS)

    # =========================
    # RETRIEVE - Product caching
    # =========================
    def retrieve(self, request, *args, **kwargs):
        pk = kwargs.get("pk")
        cache_key = product_detail_cache_key(pk)

        cached_data = cache.get(cache_key)
        if cached_data is not None:
            return set_cache_header(Response(cached_data), CACHE_HIT)

        response = super().retrieve(request, *args, **kwargs)

        cache.set(cache_key, response.data, timeout=PRODUCT_DETAIL_CACHE_TIMEOUT_SECONDS)
        return set_cache_header(response, CACHE_MISS)
