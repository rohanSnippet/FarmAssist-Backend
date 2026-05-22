from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter

# Import everything from your 'api' app
from api.views import (
    CreateUserView, 
    UserDetailView, 
    CustomTokenObtainPairView, 
    FirebaseAuthView, 
    LinkAccountView, 
    FarmViewSet, 
    FarmSeasonViewSet,
    PestAlertBroadcastViewSet, 
    PestDetectionViewSet,
    CommunityPostViewSet
)

from recommendation.views import (
    RecommendCropView, 
    UserHistoryView, 
    SoilCardOCRView, 
    MarketForecastView, 
    TopCropsForecastView
)

from rest_framework_simplejwt.views import TokenRefreshView

# Create the router for the viewsets inside your 'api' app
router = DefaultRouter()
router.register(r'farms', FarmViewSet, basename='farm')
router.register(r'detections', PestDetectionViewSet, basename='detection')
router.register(r'alerts', PestAlertBroadcastViewSet, basename='alert')
router.register(r'seasons', FarmSeasonViewSet, basename='season')
router.register(r'community-posts', CommunityPostViewSet, basename='community-post')

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # Auth & Users
    path('api/register/', CreateUserView.as_view(), name="register"),
    path('api/token/', CustomTokenObtainPairView.as_view(), name="obtain_token"),
    path('api/token/refresh/', TokenRefreshView.as_view(), name="refresh_token"),
    path('api-auth/', include("rest_framework.urls")),
    path('api/auth/firebase/', FirebaseAuthView.as_view(), name='firebase_auth'),
    path('api/auth/link/', LinkAccountView.as_view(), name='link_account'),
    path('api/me/', UserDetailView.as_view(), name='user_detail'),
    
    # Recommendations
    path('predict/', RecommendCropView.as_view(), name='predict'),
    path('history/', UserHistoryView.as_view(), name='history'),
    path('ocr-soil-card/', SoilCardOCRView.as_view(), name='ocr_soil_card'),
    path('market-forecast/', MarketForecastView.as_view(), name='market_forecast'),
    path('top-market-forecast/', TopCropsForecastView.as_view(), name='top_market_forecast'),
    
    # This single line handles /api/farms/, /api/detections/, and /api/alerts/
    path('api/', include(router.urls)),
]