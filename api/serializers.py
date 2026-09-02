# api/serializers.py
from rest_framework import serializers
from .models import User, Farm, FarmSeason, PestDetection, PestAlertBroadcast, Post
from django.contrib.gis.geos import GEOSGeometry
import json
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id","first_name", "last_name", "email", "password", "photo_url", "phone_number", "auth_providers", "location_label", "latitude", "longitude"]
        extra_kwargs = {"password": {"write_only": True}}
        read_only_fields = ["email", "auth_providers"]
    
    def validate_email(self, value):
        if User.objects.filter(email= value).exists():
            raise serializers.ValidationError("User already exists")
        return value
    
    def validate_phone_number(self, value):
        if value == "":
            return None
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
    
# Pest control 
    
class FarmSeasonSerializer(serializers.ModelSerializer):
    class Meta:
        model = FarmSeason
        fields = ['id', 'crop_name', 'planted_date', 'expected_harvest_date', 'is_active']

class FarmSerializer(serializers.ModelSerializer):
    seasons = FarmSeasonSerializer(many=True, read_only=True)
    class Meta:
        model = Farm
        fields = ['id', 'name', 'boundaries', 'created_at', 'seasons']

    def to_internal_value(self, data):
        internal_data = super().to_internal_value(data)
        if 'boundaries' in data:
            boundaries_str = data.get('boundaries')
            if isinstance(boundaries_str, dict):
                boundaries_str = json.dumps(boundaries_str)
            internal_data['boundaries'] = GEOSGeometry(boundaries_str)
        return internal_data

class PestDetectionSerializer(serializers.ModelSerializer):
    farm_id = serializers.IntegerField(write_only=True)

    class Meta:
        model = PestDetection
        fields = [
            'id',
            'farm_id',
            'farm_season',
            'pest_name',
            'severity_level',
            'image_url',
            'detection_location',
            'weather_snapshot',
            'timestamp',
        ]

        read_only_fields = [
            'id',
            'farm_season',
            'detection_location',
            'timestamp',
        ]

    def create(self, validated_data):
        validated_data.pop('farm_id', None)
        return super().create(validated_data)

class PestAlertBroadcastSerializer(serializers.ModelSerializer):
    # Pull data from the related PestDetection model for the frontend
    pest_name = serializers.CharField(source='source_detection.pest_name', read_only=True)
    severity = serializers.IntegerField(source='source_detection.severity_level', read_only=True)
    created_at = serializers.DateTimeField(source='timestamp', read_only=True)

    class Meta:
        model = PestAlertBroadcast
        # Notice we DO NOT include 'notified_users' or 'dismissed_by'. 
        # The frontend doesn't need to download huge arrays of user IDs!
        fields = ['id', 'pest_name', 'severity', 'max_risk_score', 'created_at']
        
class PostSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()
    author_initials = serializers.SerializerMethodField()
    
    class Meta:
        model = Post
        fields = [
            'id', 'author', 'author_name', 'author_initials', 
            'content', 'content_hi', 'content_mr', 'category', 
            'image_url', 'likes_count', 'created_at'
        ]
        read_only_fields = ['author', 'likes_count', 'content_hi', 'content_mr', 'created_at']

    def get_author_name(self, obj):
        """Returns the full name of the author, falling back to username if names aren't set."""
        if obj.author.first_name or obj.author.last_name:
            return f"{obj.author.first_name} {obj.author.last_name}".strip()
        return obj.author.username

    def get_author_initials(self, obj):
        """Generates the 1 or 2 letter initials for the frontend avatar."""
        name = self.get_author_name(obj)
        parts = name.split()
        
        if len(parts) >= 2:
            return f"{parts[0][0]}{parts[-1][0]}".upper()
        elif len(parts) == 1 and len(parts[0]) > 0:
            return f"{parts[0][0]}".upper()
        return "U" # Default fallback
        
    def create(self, validated_data):
        """
        Automatically assigns the logged-in user making the request 
        as the author of the post.
        """
        request = self.context.get('request')
        if request and hasattr(request, 'user'):
            validated_data['author'] = request.user
        return super().create(validated_data)


