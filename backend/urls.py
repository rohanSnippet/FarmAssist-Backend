
from django.contrib import admin
from django.urls import path, include
from api.views import CreateUserView, UserDetailView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/register/', CreateUserView.as_view(), name="register"),
    path('api/token/', TokenObtainPairView.as_view(), name="obtain_token"),
    path('api/token/refresh/', TokenRefreshView.as_view(), name="refresh_token"),
    path('api-auth/', include("rest_framework.urls")),
    path('user/me/', UserDetailView.as_view(), name='user_detail')
]
