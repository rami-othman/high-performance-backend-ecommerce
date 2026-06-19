from rest_framework import viewsets
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from django.core.cache import cache

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
        cache_key = "products_list"

        cached_data = cache.get(cache_key)
        if cached_data is not None:
            return Response(cached_data)

        response = super().list(request, *args, **kwargs)

        cache.set(cache_key, response.data, timeout=60)
        return response

    # =========================
    # RETRIEVE - Product caching
    # =========================
    def retrieve(self, request, *args, **kwargs):
        pk = kwargs.get("pk")
        cache_key = f"product_{pk}"

        cached_data = cache.get(cache_key)
        if cached_data is not None:
            return Response(cached_data)

        response = super().retrieve(request, *args, **kwargs)

        cache.set(cache_key, response.data, timeout=120)
        return response