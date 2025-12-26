
from django.contrib import admin
from django.urls import path, include
from api.views import CreateUserView, UserDetailView, CustomTokenObtainPairView, FirebaseAuthView, LinkAccountView
from recommendation.views import RecommendCropView, UserHistoryView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/register/', CreateUserView.as_view(), name="register"),
    path('api/token/', CustomTokenObtainPairView.as_view(), name="obtain_token"),
    path('api/token/refresh/', TokenRefreshView.as_view(), name="refresh_token"),
    path('api-auth/', include("rest_framework.urls")),
    path('api/auth/firebase/', FirebaseAuthView.as_view(), name='firebase_auth'),
    # Link Email/Google to Phone Account
    path('api/auth/link/', LinkAccountView.as_view(), name='link_account'),
    path('user/me/', UserDetailView.as_view(), name='user_detail'),
    path('predict/', RecommendCropView.as_view(), name='predict'),
    path('history/', UserHistoryView.as_view(), name='history'),
]
