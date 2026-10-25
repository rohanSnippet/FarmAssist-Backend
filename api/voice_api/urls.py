from django.urls import path
from .views import LiveKitTokenView

urlpatterns = [
    path('token/', LiveKitTokenView.as_view(), name='voice-token'),
]
