from django.shortcuts import render
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated, AllowAny
from .models import User
from .serializers import UserSerializer

# 1. Registration View
# This handles the creation of a new user.
# We use AllowAny because a user must be able to register without being logged in.
class CreateUserView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [AllowAny] 

# 2. Example Protected View
# This is just to test if your authentication is working.
# It returns the details of the currently logged-in user.
class UserDetailView(generics.RetrieveAPIView):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated] # Only logged-in users can access this

    def get_object(self):
        # Overriding this method to return the user making the request
        return self.request.user