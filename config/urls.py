from django.contrib import admin
from django.urls import include, path
from django.views.generic import TemplateView
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView


urlpatterns = [
    path("admin/", admin.site.urls),
    path("", TemplateView.as_view(template_name="home.html"), name="home"),
    path("products-ui/", TemplateView.as_view(template_name="products.html"), name="products-ui"),
    path("cart-ui/", TemplateView.as_view(template_name="cart.html"), name="cart-ui"),
    path("orders-ui/", TemplateView.as_view(template_name="orders.html"), name="orders-ui"),
    path("dashboard/", TemplateView.as_view(template_name="dashboard.html"), name="dashboard"),
    path("api/products/", include("products.urls")),
    path("api/cart/", include("cart.urls")),
    path("api/orders/", include("orders.urls")),
    path("api/reports/", include("reports.urls")),
    path("api/performance/", include("performance.urls")),
    path("api/", include("performance.system_urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
]
