from rest_framework import generics, viewsets, status, permissions
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.pagination import CursorPagination
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.views import APIView
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from .models import User, Farm, FarmSeason, PestDetection, PestAlertBroadcast, Post, PostUpvote, CropScanJob, UserNotification
from .serializers import UserSerializer, CustomTokenObtainPairSerializer, UpdateProfileSerializer, FarmSerializer,FarmSeasonSerializer, PestDetectionSerializer, PestAlertBroadcastSerializer, PostSerializer, PostCommentSerializer, CropScanJobSerializer, UserNotificationSerializer
from django.db.models import F

# Cloudinary is optional. If the package is not installed, we gracefully
# fall back to saving the uploaded file to Django's configured storage
# (the `Post.image` ImageField).
try:
    import cloudinary.uploader as cloudinary_uploader
    _CLOUDINARY_AVAILABLE = True
except Exception:
    cloudinary_uploader = None
    _CLOUDINARY_AVAILABLE = False
from firebase_admin import auth, credentials
import os, time, json, firebase_admin
from django.utils.timezone import now
from django_filters.rest_framework import DjangoFilterBackend
from django.conf import settings
from django.core.cache import cache
from django.shortcuts import get_object_or_404
from django.contrib.gis.geos import Point
from .tasks import calculate_pest_spread, run_crop_scan_task
from .ai_engine import process_crop_diagnostic_pipeline

if not firebase_admin._apps:
    firebase_env = os.getenv("FIREBASE_CREDENTIALS")
    
    if firebase_env:
        cred = credentials.Certificate(json.loads(firebase_env))
    """  else:
        cred_path = os.path.join(settings.BASE_DIR, "serviceAccountKey.json")
        cred = credentials.Certificate(cred_path) """
    
    firebase_admin.initialize_app(cred)

# ===================================
# User
# =================================== 
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

# ==========================================================
# Farms
# ==========================================================
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

# =============================================================
#Pest
# =============================================================
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

        # Guard 1: farm_id must be present in the request
        if not farm_id:
            raise ValidationError({
                "code": "MISSING_FARM_ID",
                "message": "No farm was selected. Please choose a farm before broadcasting a pest alert."
            })

        # Guard 2: The farm must exist and belong to the logged-in user
        try:
            farm = Farm.objects.get(id=farm_id, user=self.request.user)
        except Farm.DoesNotExist:
            raise ValidationError({
                "code": "FARM_NOT_FOUND",
                "message": "The selected farm could not be found. It may have been deleted or does not belong to your account."
            })

        # Guard 3: The farm must have a mapped boundary polygon
        if not farm.boundaries:
            raise ValidationError({
                "code": "FARM_NO_BOUNDARY",
                "message": f"Farm '{farm.name}' has no mapped boundary. Please draw your farm boundary on the map before broadcasting."
            })

        # Guard 4: The farm must have an active crop season (not fallow land)
        active_season = FarmSeason.objects.filter(farm=farm, is_active=True).first()
        if not active_season:
            raise ValidationError({
                "code": "FALLOW_LAND",
                "message": f"Farm '{farm.name}' is currently fallow (no active crop). Plant a crop on this land before logging a pest detection."
            })

        # Derive the detection point from the farm's centroid (no device GPS dependency)
        detection_point = farm.boundaries.centroid

        # Save the detection record
        detection = serializer.save(
            farm_season=active_season,
            detection_location=detection_point
        )

        # Trigger the lightweight background broadcast task using threading
        try:
            import threading
            thread = threading.Thread(target=calculate_pest_spread, args=(detection.id,))
            thread.start()
        except Exception as e:
            # Non-fatal: detection is already saved, broadcast failure should not roll back the detection
            import logging
            logging.getLogger(__name__).error(
                f"[PestDetection] threading broadcast task failed to queue for detection {detection.id}: {e}"
            )
    
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

# =============================================================
# Community
# ============================================================
class FeedCursorPagination(CursorPagination):
    page_size = 10
    ordering = '-created_at'

class PostViewSet(viewsets.ModelViewSet):
    serializer_class = PostSerializer
    pagination_class = FeedCursorPagination
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    parser_classes = [MultiPartParser, FormParser]

    def get_queryset(self):
        queryset = Post.objects.select_related('author').all()
        category = self.request.query_params.get('category')
        district = self.request.query_params.get('district')
        crop = self.request.query_params.get('crop')
        urgent = self.request.query_params.get('urgent')

        if category and category.upper() != 'ALL':
            queryset = queryset.filter(category=category.upper())
        if district and district.strip():
            queryset = queryset.filter(district__iexact=district.strip())
        if crop and crop.strip():
            queryset = queryset.filter(crop_tag__iexact=crop.strip())
        if urgent == 'true':
            queryset = queryset.filter(is_urgent=True)

        return queryset

    def perform_create(self, serializer):
        user = self.request.user
        district = self.request.data.get('district') or getattr(user, 'location_label', '')
        # If an image file is included in the multipart form, upload to Cloudinary
        image_file = None
        if hasattr(self.request, 'FILES') and 'image' in self.request.FILES:
            image_file = self.request.FILES.get('image')

        extra = {
            'author': user,
            'district': district,
            'latitude': getattr(user, 'latitude', None),
            'longitude': getattr(user, 'longitude', None)
        }

        if image_file:
            if _CLOUDINARY_AVAILABLE and cloudinary_uploader is not None:
                try:
                    # cloudinary expects a file-like object; pass directly
                    upload_result = cloudinary_uploader.upload(image_file)
                    secure_url = upload_result.get('secure_url')
                    if secure_url:
                        extra['image_url'] = secure_url
                except Exception as e:
                    # Log and continue — fail the upload gracefully instead of breaking the whole post
                    print(f"Cloudinary upload failed: {e}")
                    # Fall back to saving the file locally to the ImageField
                    extra['image'] = image_file
            else:
                # Cloudinary not available: save to model ImageField via serializer
                extra['image'] = image_file

        serializer.save(**extra)
        # Invalidate page 1 caches across all categories
        cache.delete_pattern("feed_page_1_*")

    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def upvote(self, request, pk=None):
        post = self.get_object()
        user = request.user
        upvote_record = PostUpvote.objects.filter(post=post, user=user)

        if upvote_record.exists():
            upvote_record.delete()
            Post.objects.filter(id=post.id).update(upvotes_count=F('upvotes_count') - 1)
            has_upvoted = False
        else:
            PostUpvote.objects.create(post=post, user=user)
            Post.objects.filter(id=post.id).update(upvotes_count=F('upvotes_count') + 1)
            has_upvoted = True

        post.refresh_from_db()
        return Response({
            'upvotes_count': post.upvotes_count,
            'has_upvoted': has_upvoted
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get', 'post'], permission_classes=[permissions.IsAuthenticatedOrReadOnly])
    def comments(self, request, pk=None):
        post = self.get_object()
        if request.method == 'GET':
            comments = post.comments.select_related('author').all()
            serializer = PostCommentSerializer(comments, many=True)
            return Response(serializer.data)

        elif request.method == 'POST':
            serializer = PostCommentSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            serializer.save(author=request.user, post=post)
            Post.objects.filter(id=post.id).update(comments_count=F('comments_count') + 1)
            return Response(serializer.data, status=status.HTTP_201_CREATED)


# ======================================================================
# Async Crop Scan Queue
# ======================================================================

class CropScanSubmitView(APIView):
    """
    POST /api/scan/submit/

    Accepts a multipart image upload, persists it as a CropScanJob row,
    and immediately queues the AI pipeline as a Celery background task.
    Returns 202 Accepted with the job_id so the frontend can poll later.
    """
    permission_classes = [IsAuthenticated]
    parser_classes     = [MultiPartParser, FormParser]

    def post(self, request):
        image_file = request.FILES.get('image')
        if not image_file:
            return Response(
                {"code": "MISSING_IMAGE", "message": "No image was uploaded. Please attach a crop image."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        crop_hint = request.data.get('crop_hint', '').strip()
        language  = request.data.get('language', 'en').strip() or 'en'

        # Read image bytes and persist in DB so no shared filesystem is needed
        image_bytes = image_file.read()

        job = CropScanJob.objects.create(
            user       = request.user,
            status     = CropScanJob.Status.PENDING,
            crop_hint  = crop_hint,
            language   = language,
            image_data = image_bytes,
        )

        # The task is picked up by the sequential queue worker running in apps.py


        return Response(
            {
                "job_id":     job.id,
                "status":     job.status,
                "created_at": job.created_at,
                "message":    "Scan queued. Your result will be ready shortly.",
            },
            status=status.HTTP_202_ACCEPTED,
        )


class CropScanJobViewSet(viewsets.ModelViewSet):
    """
    GET /api/scan/jobs/       — list all scan jobs for the logged-in user (newest first)
    GET /api/scan/jobs/{id}/  — retrieve one job with full result payload
    DELETE /api/scan/jobs/{id}/ - delete a job
    """
    permission_classes = [IsAuthenticated]
    serializer_class   = CropScanJobSerializer
    http_method_names  = ['get', 'delete']

    def get_queryset(self):
        return CropScanJob.objects.filter(user=self.request.user)

class UserNotificationViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = UserNotificationSerializer

    def get_queryset(self):
        return UserNotification.objects.filter(user=self.request.user).order_by('-created_at')

    def partial_update(self, request, *args, **kwargs):
        notification = self.get_object()
        notification.is_read = True
        notification.save(update_fields=['is_read'])
        return Response({"status": "marked as read"})

class CropScanJobImageView(APIView):
    """
    Returns the binary image data for a CropScanJob.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk, *args, **kwargs):
        job = get_object_or_404(CropScanJob, pk=pk, user=request.user)
        if not job.image_data:
            return Response({"error": "No image found for this job."}, status=404)
        
        # We assume the image is standard JPEG/PNG since it's from the device camera
        from django.http import HttpResponse
        return HttpResponse(job.image_data, content_type="image/jpeg")

# ──────────────────────────────────────────────────────────────────────
# SSE View
# ──────────────────────────────────────────────────────────────────────
from django.http import StreamingHttpResponse
import queue

def stream_notifications(request):
    """
    SSE endpoint. Clients connect here to receive real-time notifications.
    Since EventSource cannot send headers, we expect a ?token=... in the query params.
    """
    token = request.GET.get('token')
    if not token:
        return StreamingHttpResponse("Unauthorized", status=401)
    
    from rest_framework_simplejwt.tokens import AccessToken
    from django.contrib.auth import get_user_model
    User = get_user_model()
    
    try:
        access_token = AccessToken(token)
        user = User.objects.get(id=access_token['user_id'])
    except Exception:
        return StreamingHttpResponse("Unauthorized", status=401)
    
    def event_stream():
        from .sse import add_stream, remove_stream
        q = queue.Queue()
        add_stream(user.id, q)
        try:
            # Yield initial connection success
            yield f"data: {{\"type\": \"connected\"}}\n\n"
            
            while True:
                # Wait for an event with timeout to keep connection alive
                try:
                    event_data = q.get(timeout=30)
                    yield f"data: {event_data}\n\n"
                except queue.Empty:
                    yield f"data: {{\"type\": \"ping\"}}\n\n"
        except Exception:
            pass
        finally:
            remove_stream(user.id, q)
            
    response = StreamingHttpResponse(event_stream(), content_type='text/event-stream')
    response['Cache-Control'] = 'no-cache'
    return response
