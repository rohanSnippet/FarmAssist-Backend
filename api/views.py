from rest_framework import generics
from rest_framework.permissions import IsAuthenticated, AllowAny
from .models import User, Farm, FarmSeason, PestDetection, PestAlert
from .serializers import UserSerializer, CustomTokenObtainPairSerializer, UpdateProfileSerializer, FarmSerializer,FarmSeasonSerializer, PestDetectionSerializer, PestAlertSerializer
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.views import APIView
import firebase_admin
from rest_framework.decorators import action
from firebase_admin import auth, credentials
from rest_framework.response import Response
import os, time
from django.utils.timezone import now
import json
from django.conf import settings
from rest_framework import viewsets, status
from .tasks import calculate_pest_spread
from rest_framework.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from rest_framework.parsers import FormParser, MultiPartParser
from django.contrib.gis.geos import Point
from .ai_engine import analyze_crop_image


if not firebase_admin._apps:
    firebase_env = os.getenv("FIREBASE_CREDENTIALS")
    
    if firebase_env:
        cred = credentials.Certificate(json.loads(firebase_env))
    """  else:
        cred_path = os.path.join(settings.BASE_DIR, "serviceAccountKey.json")
        cred = credentials.Certificate(cred_path) """
    
    firebase_admin.initialize_app(cred)
    
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

# Note: You can DELETE 'CreateUserView' and 'CustomTokenObtainPairView' 
# if you migrate fully to this flow, as they are no longer needed.

""" class FirebaseAuthView(APIView):

    permission_classes = [AllowAny]

    def post(self, request):
        id_token = request.data.get('token')
        mode = request.data.get('mode') # 'login' or 'signup'

        if not id_token:
            return Response({'error': 'No token provided'}, status=400)

        try:
            # 1. Verify Token with Firebase
            decoded_token = auth.verify_id_token(id_token)
            
            # Extract Identity Data
            uid = decoded_token['uid']
            email = decoded_token.get('email')
            phone = decoded_token.get('phone_number') # e.g., +919999999999
            
            # Determine Provider (google.com, phone, password, etc.)
            firebase_provider_id = decoded_token.get('firebase', {}).get('sign_in_provider')
            print(f"Provider ID: {firebase_provider_id}")
            # Map Firebase provider IDs to your readable names
            provider_map = {
                'google.com': 'google',
                'phone': 'phone',
                'password': 'email'
            }
            current_provider = provider_map.get(firebase_provider_id, firebase_provider_id)

            user = None

            # --- LOGIC BRANCH 1: User has Email (Google Login) ---
            if email:
                try:
                    user = User.objects.get(email=email)
                    
                    # Requirement 2: User exists, just link/update provider list
                    if current_provider not in user.auth_providers:
                       if not user.photo_url: 
                        user.photo_url = decoded_token.get('picture') or decoded_token.get('photo_url')
                        user.auth_providers.append(current_provider)
                        user.last_login = now()
                        user.save()
                        
                except User.DoesNotExist:
                    # if mode == 'login':
                    #     return Response({'error': 'Account not found. Please sign up.'}, status=404)
                    password = request.data.get("password") if current_provider == "email" else None
                    
                    # Create New User (Google)
                    user = User.objects.create_user(
                        email=email,
                        password=password, 
                        first_name=decoded_token.get('name', '').split(' ')[0],
                        last_name=' '.join(decoded_token.get('name', '').split(' ')[1:]) if decoded_token.get('name') else '',
                        photo_url=decoded_token.get('picture') or decoded_token.get('photo_url'),
                        last_login=now(),
                        phone_number=None,
                        auth_providers=[current_provider]
                    )

            # --- LOGIC BRANCH 2: User has Phone (Phone Login) ---
            elif phone:
                try:
                    user = User.objects.get(phone_number=phone)
                    
                    # Update provider list if needed
                    if current_provider not in user.auth_providers:
                        user.auth_providers.append(current_provider)
                        user.last_login = now()
                        user.save()

                except User.DoesNotExist:
                    # Requirement 4: Strict Login Check
                    if mode == 'login':
                        return Response({'error': 'No account linked to this phone number.'}, status=404)
                    
                    # Requirement 3: Signup Check 
                    # (Implicitly passed since we are in Except block)
                    
                    # Create New User (Phone)
                    # Use dummy email as placeholder
                    placeholder_email = f"{uid}@phone.farmassist"
                    
                    user = User.objects.create_user(
                        email=placeholder_email,
                        phone_number=phone,
                        first_name="Farmer",
                        last_login=now(),
                        auth_providers=[current_provider]
                    )

            if not user:
                return Response({'error': 'Authentication failed.'}, status=400)

            # Generate JWT Tokens
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
"""


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
    
    
# Pest control

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
            ai_result = analyze_crop_image(image_file)
            
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

        # 3. Parse the GeoJSON location sent from React
        location_data = self.request.data.get('detection_location')
        # If no GPS was available, default to the center of their farm
        if not location_data:
            detection_point = farm.boundaries.centroid
        else:
            # Assuming React sends standard GeoJSON string or dict
            import json
            loc_dict = json.loads(location_data) if isinstance(location_data, str) else location_data
            coords = loc_dict.get('coordinates')
            detection_point = Point(coords[0], coords[1], srid=4326)

        # 4. Save the record, link the active season, and trigger Celery!
        detection = serializer.save(
            farm_season=active_season,
            detection_location=detection_point
        )
        
        # TODO: Trigger your Celery task here!
        # process_pest_alert.delay(detection.id)

class PestAlertViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PestAlertSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return PestAlert.objects.filter(target_farm__user=self.request.user).order_by('-timestamp')