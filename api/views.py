from rest_framework import generics
from rest_framework.permissions import IsAuthenticated, AllowAny
from .models import User
from .serializers import UserSerializer, CustomTokenObtainPairSerializer, UpdateProfileSerializer
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.views import APIView
import firebase_admin
from firebase_admin import auth, credentials
from rest_framework.response import Response
import os
from django.utils.timezone import now
import json
from django.conf import settings


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
class UserDetailView(generics.RetrieveAPIView):
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
    """
    Unified Login/Signup for Google, Email/Password & Phone.
    Accepts a Firebase ID Token, verifies it, and returns Django JWTs.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        id_token = request.data.get('token')
        
        # We don't strictly need 'mode' anymore, but can keep it for specific logic
        # mode = request.data.get('mode') 

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
                    username=None, # Ensure we don't set username if your model doesn't use it
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