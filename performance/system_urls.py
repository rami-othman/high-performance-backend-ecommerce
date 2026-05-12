from django.urls import path

from .views import HealthView, ServerInfoView


urlpatterns = [
    path("health/", HealthView.as_view(), name="health"),
    path("server-info/", ServerInfoView.as_view(), name="server-info"),
]
