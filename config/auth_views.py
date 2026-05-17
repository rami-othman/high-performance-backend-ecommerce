from rest_framework import generics
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .auth_serializers import RegisterSerializer, UserSerializer


class ScopedTokenObtainPairView(TokenObtainPairView):
    throttle_scope = "auth"


class ScopedTokenRefreshView(TokenRefreshView):
    throttle_scope = "auth"


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]
    throttle_scope = "auth"


class MeView(APIView):
    permission_classes = [IsAuthenticated]
    throttle_scope = "auth"

    def get(self, request):
        return Response(UserSerializer(request.user).data)
