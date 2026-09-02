from rest_framework import generics, viewsets, status
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.pagination import CursorPagination
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.views import APIView
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from .models import User, Farm, FarmSeason, PestDetection, PestAlertBroadcast, Post
from .serializers import UserSerializer, CustomTokenObtainPairSerializer, UpdateProfileSerializer, FarmSerializer,FarmSeasonSerializer, PestDetectionSerializer, PestAlertBroadcastSerializer, PostSerializer
from firebase_admin import auth, credentials
import os, time, json, firebase_admin
from django.utils.timezone import now
from django_filters.rest_framework import DjangoFilterBackend
from django.conf import settings
from django.core.cache import cache
from django.shortcuts import get_object_or_404
from django.contrib.gis.geos import Point
from .tasks import calculate_pest_spread
from .ai_engine import process_crop_diagnostic_pipeline

if not firebase_admin._apps:
    firebase_env = os.getenv("FIREBASE_CREDENTIALS")
    
    if firebase_env:
        cred = credentials.Certificate(json.loads(firebase_env))
    """  else:
        cred_path = os.path.join(settings.BASE_DIR, "serviceAccountKey.json")
        cred = credentials.Certificate(cred_path) """
    
    firebase_admin.initialize_app(cred)
    
# 1. Registration View
class CreateUserView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [AllowAny] 

# 2. Example Protected View
class UserDetailView(generics.RetrieveUpdateAPIView):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated] # Only logged-in users can access this

    def get_object(self):
        # Overriding this method to return the user making the request
        return self.request.user
    
class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer

# New Firebase Auth veiw
class FirebaseAuthView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        id_token = request.data.get('token')
        
        if not id_token:
            return Response({'error': 'No token provided'}, status=400)

        try:
            # 1. Verify Token with Firebase
            decoded_token = auth.verify_id_token(id_token)
            
            # Extract Identity Data
            uid = decoded_token['uid']
            email = decoded_token.get('email')
            phone = decoded_token.get('phone_number')
            
            # Determine Provider
            firebase_provider_id = decoded_token.get('firebase', {}).get('sign_in_provider')
            provider_map = {
                'google.com': 'google',
                'phone': 'phone',
                'password': 'email' # Both standard email signup and google fall here sometimes
            }
            current_provider = provider_map.get(firebase_provider_id, firebase_provider_id)

            user = None

            # --- STRATEGY: Find User by Email or Phone ---
            if email:
                user = User.objects.filter(email=email).first()
            elif phone:
                user = User.objects.filter(phone_number=phone).first()

            # --- CREATE USER IF NOT EXISTS ---
            if not user:
                # If authenticating via Phone, we need a dummy email
                user_email = email if email else f"{uid}@phone.farmassist"
                
                user = User.objects.create_user(
                    email=user_email,
                    # username=None, # Ensure we don't set username if your model doesn't use it
                    first_name=decoded_token.get('name', 'Farmer').split(' ')[0],
                    phone_number=phone,
                    auth_providers=[current_provider]
                )
                # CRITICAL: Set password to unusable so they CANNOT login via standard Django auth
                user.set_unusable_password()
                user.save()
            
            # --- UPDATE EXISTING USER INFO ---
            else:
                # Update provider list if this is a new method for them
                if current_provider not in user.auth_providers:
                    user.auth_providers.append(current_provider)
                
                # Update photo if missing
                if not user.photo_url:
                     user.photo_url = decoded_token.get('picture') or decoded_token.get('photo_url')
                
                user.last_login = now()
                user.save()

            # 2. Generate Django JWT Tokens
            refresh = RefreshToken.for_user(user)
            refresh['email'] = user.email

            return Response({
                'refresh': str(refresh),
                'access': str(refresh.access_token),
                'user': UserSerializer(user).data
            })

        except Exception as e:
            print(f"Auth Error: {e}")
            return Response({'error': 'Invalid Token'}, status=401)

class LinkAccountView(APIView):
    """
    Requirement 5: User updates email or links Google to existing Phone account.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = UpdateProfileSerializer(data=request.data)
        
        if serializer.is_valid():
            new_email = serializer.validated_data['email']
            new_provider = serializer.validated_data.get('provider', 'email')
            
            user = request.user
            
            # Update Email
            user.email = new_email
            
            # Update Providers List
            # We fetch current list, append new one, and ensure uniqueness using set
            providers = set(user.auth_providers)
            providers.add(new_provider)
            user.auth_providers = list(providers)
            
            user.save()
            
            return Response({
                "message": "Account linked successfully", 
                "user": UserSerializer(user).data
            })
        
        return Response(serializer.errors, status=400)
    
#Farms
class FarmViewSet(viewsets.ModelViewSet):
    serializer_class = FarmSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Farm.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

class FarmSeasonViewSet(viewsets.ModelViewSet):
    serializer_class = FarmSeasonSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        # Security: Only return seasons for farms owned by the logged-in user
        return FarmSeason.objects.filter(farm__user=self.request.user)

    def perform_create(self, serializer):
        # 1. Manually extract the farm ID sent from the React frontend
        farm_id = self.request.data.get('farm')
        
        if not farm_id:
            raise ValidationError({"farm": "You must provide a farm ID to plant a crop."})

        # 2. Security Check: Ensure the farm exists AND the logged-in user owns it
        try:
            farm_instance = Farm.objects.get(id=farm_id, user=self.request.user)
        except Farm.DoesNotExist:
            raise ValidationError({"farm": "Invalid farm ID or you do not have permission."})

        # 3. Forcefully inject the verified farm instance into the save method
        new_season = serializer.save(farm=farm_instance)
        
        # 4. Smart Cleanup: Deactivate all OTHER seasons for this specific farm
        FarmSeason.objects.filter(
            farm=farm_instance, 
            is_active=True
        ).exclude(id=new_season.id).update(is_active=False)

#Pest
class PestDetectionViewSet(viewsets.ModelViewSet):
    serializer_class = PestDetectionSerializer
    parser_classes = [MultiPartParser, FormParser]
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return PestDetection.objects.filter(farm_season__farm__user=self.request.user)

   # ---------------------------------------------------------
    # 1. THE AI SCANNER ENDPOINT (/api/detections/scan/)
    # ---------------------------------------------------------
    @action(detail=False, methods=['post'])
    def scan(self, request):
        image_file = request.FILES.get('image')
        
        if not image_file:
            raise ValidationError({"image": "Please upload an image of the crop."})

        try:
            # 1. Pass the image to the Gemini Vision Engine
            ai_result = process_crop_diagnostic_pipeline(image_file)
            
            # 2. CRITICAL: Reset the file pointer! 
            # Because Gemini read the file bytes, the pointer is at the end of the file. 
            # We must reset it to 0 so your "Smart Saver" can save it to Postgres later.
            image_file.seek(0) 

            return Response(ai_result, status=status.HTTP_200_OK)
            
        except ValueError as e:
            # This catches our custom errors (like missing JSON keys)
            raise ValidationError({"image": str(e)})
        except Exception as e:
            # Catch-all for unexpected API failures
            print(f"Scan API Error: {e}")
            return Response(
                {"error": "AI processing failed. Please try again."}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    # ---------------------------------------------------------
    # 2. THE SMART SAVER (Triggered on POST /api/detections/)
    # ---------------------------------------------------------
    def perform_create(self, serializer):
        farm_id = self.request.data.get('farm_id')
        
        # 1. Verify the farm exists and belongs to the user
        try:
            farm = Farm.objects.get(id=farm_id, user=self.request.user)
        except Farm.DoesNotExist:
            raise ValidationError({"farm_id": "Invalid Farm ID."})

        # 2. Find the ACTIVE crop season for this farm
        active_season = FarmSeason.objects.filter(farm=farm, is_active=True).first()
        if not active_season:
            raise ValidationError({"farm_id": "You must plant a crop on this land before logging a pest."})

        # 3. MAGIC FIX: Ignore device GPS entirely. 
        # Force the detection point to be the exact mathematical center of the Farm's polygon.
        detection_point = farm.boundaries.centroid

        # 4. Save the record
        detection = serializer.save(
            farm_season=active_season,
            detection_location=detection_point
        )
        
        # 5. Trigger the Celery Broadcast Task
        calculate_pest_spread.delay(detection.id)
    
class PestAlertBroadcastViewSet(viewsets.ModelViewSet):
    # Ensure you create a simple serializer for PestAlertBroadcast in serializers.py
    serializer_class = PestAlertBroadcastSerializer 
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user_id = self.request.user.id
        
        # MAGIC: Find broadcasts where 'notified_users' contains my ID, 
        # BUT 'dismissed_by' DOES NOT contain my ID.
        return PestAlertBroadcast.objects.filter(
            notified_users__contains=user_id
        ).exclude(
            dismissed_by__contains=user_id
        ).order_by('-timestamp')

    # Custom logic to handle the "Dismiss" click
    def partial_update(self, request, *args, **kwargs):
        alert = self.get_object()
        user_id = request.user.id
        
        # Add the user to the dismissed list and save
        if user_id not in alert.dismissed_by:
            alert.dismissed_by.append(user_id)
            alert.save(update_fields=['dismissed_by'])
            
        return Response({"status": "dismissed successfully"})
    
#Post
class FeedCursorPagination(CursorPagination):
    page_size = 10
    ordering = '-created_at' 

class PostViewSet(viewsets.ModelViewSet):
    queryset = Post.objects.select_related('author').all()
    serializer_class = PostSerializer
    pagination_class = FeedCursorPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['category']

    def list(self, request, *args, **kwargs):
        category = request.query_params.get('category', 'All')
        cursor = request.query_params.get('cursor')
        
        # Only cache the first page. Cursors are dynamic.
        cache_key = f"feed_page_1_{category}"
        
        if not cursor:
            cached_data = cache.get(cache_key)
            if cached_data:
                return Response(cached_data)

        response = super().list(request, *args, **kwargs)
        
        if not cursor:
            cache.set(cache_key, response.data, timeout=60 * 15) # Cache for 15 mins
            
        return response

class CropScannerAPIView(APIView):
    parser_classes = (MultiPartParser, FormParser)

    def post(self, request, *args, **kwargs):
        image_file = request.FILES.get('image')
        crop_hint = request.data.get('crop', None)
        
        # Extract language code from query param, body, or HTTP Accept-Language header
        # Defaults to 'en' (matching React i18next config)
        lang_code = (
            request.data.get('language') or 
            request.headers.get('Accept-Language', 'en')[:2].lower()
        )

        if not image_file:
            return Response(
                {"error": "No image file provided."}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        image_bytes = image_file.read()

        # Run pipeline
        diagnostic_result = process_crop_diagnostic_pipeline(
            image_bytes=image_bytes,
            crop_hint=crop_hint,
            lang_code=lang_code
        )

        # Persist scan history if user is authenticated
        if request.user.is_authenticated:
            try:
                PestDetection.objects.create(
                    user=request.user,
                    crop_type=diagnostic_result.get("crop", "Unknown"),
                    pest_name=diagnostic_result.get("primary_diagnosis", "Unknown"),
                    confidence=diagnostic_result.get("confidence", 0.0),
                    recommendations=diagnostic_result.get("advisory", "")
                )
            except Exception as e:
                # Non-fatal database logging failure
                pass

        return Response(diagnostic_result, status=status.HTTP_200_OK)
