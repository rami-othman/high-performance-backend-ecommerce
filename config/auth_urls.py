from django.urls import path

from .auth_views import MeView, RegisterView, ScopedTokenObtainPairView, ScopedTokenRefreshView


urlpatterns = [
    path("token/", ScopedTokenObtainPairView.as_view(), name="token-obtain-pair"),
    path("token/refresh/", ScopedTokenRefreshView.as_view(), name="token-refresh"),
    path("register/", RegisterView.as_view(), name="register"),
    path("me/", MeView.as_view(), name="me"),
]
