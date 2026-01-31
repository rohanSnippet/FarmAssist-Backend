# api/serializers.py
from rest_framework import serializers
from .models import User
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id","first_name", "last_name", "email", "password", "photo_url", "phone_number", "auth_providers"]
        extra_kwargs = {"password": {"write_only": True}}
        read_only_feilds = ["email", "auth_providers"]
    
    def validate_email(self, value):
        if User.objects.filter(email= value).exists():
            raise serializers.ValidationError("User already exists")
        return value
    
    def create(self, validated_data):
        # We use create_user to ensure password hashing happens
        user = User.objects.create_user(**validated_data)
        return user
    
class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):

        token = super().get_token(user)

        # 2. Add custom claims
        token['email'] = user.email
        # You can add more fields here if you want:
        # token['username'] = user.username
        # token['is_admin'] = user.is_superuser

        return token
    
class UpdateProfileSerializer(serializers.Serializer):
    """
    Used when a user (e.g., logged in via Phone) wants to add an Email/Google account.
    """
    email = serializers.EmailField()
    provider = serializers.CharField(required=False) # e.g., 'google'

    def validate_email(self, value):
        # REQUIREMENT 5: Check if email exists in another account before allowing update
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("This email is already associated with another account.")
        return value