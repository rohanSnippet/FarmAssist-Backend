from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.contrib.gis.db import models
import io, sys
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.conf import settings

# User
class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('The Email field must be set')
        email = self.normalize_email(email)
        
        if not extra_fields.get('first_name'):
            raise ValueError("First name is required")
        
        if 'auth_providers' not in extra_fields:
            extra_fields['auth_providers'] = ['email']

        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('auth_providers', ['email'])
        return self.create_user(email, password, **extra_fields)

class User(AbstractUser):
    username = None  # Remove the username field
    email = models.EmailField(unique=True)  # Make email the unique identifier
    first_name = models.CharField(max_length=150, blank=False)  # required
    last_name = models.CharField(max_length=150, blank=True)    # optional
    photo_url = models.URLField(blank=True, null=True)
    phone_number = models.CharField(max_length=20, unique=True, blank=True, null=True)
    auth_providers = models.JSONField(default=list, blank=True)
    location_label = models.CharField(max_length=255, blank=True, null=True, help_text="e.g. Mumbai, India")
    latitude = models.FloatField(blank=True, null=True)
    longitude = models.FloatField(blank=True, null=True)
    
    USERNAME_FIELD = 'email'  # Tell Django to use email for login
    REQUIRED_FIELDS = ['first_name']      # Email is required by default, so leave this empty

    objects = UserManager()

    def __str__(self):
        return self.email
    
# Farm Creation
class Farm(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='farms')
    name = models.CharField(max_length=255)
    # Stores exact boundaries drawn by the farmer
    boundaries = models.PolygonField(geography=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class FarmSeason(models.Model):
    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, related_name='seasons')
    crop_name = models.CharField(max_length=100)
    planted_date = models.DateField(auto_now_add=True)
    expected_harvest_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

#Pest Detection
class PestDetection(models.Model):
    farm_season = models.ForeignKey(FarmSeason, on_delete=models.CASCADE, related_name='detections')
    pest_name = models.CharField(max_length=255)
    severity_level = models.IntegerField(default=1)
    image_url = models.URLField(blank=True, null=True)
    detection_location = models.PointField(geography=True)
    weather_snapshot = models.JSONField(default=dict, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

class PestAlertBroadcast(models.Model):
    source_detection = models.ForeignKey(PestDetection, on_delete=models.CASCADE, related_name='broadcasts')
    max_risk_score = models.FloatField()
    
    # The "Compressed Copies": Simple JSON arrays storing User IDs
    notified_users = models.JSONField(default=list)  # e.g., [1, 44, 89]
    dismissed_by = models.JSONField(default=list)    # e.g., [44] (User 44 swiped it away)
    
    timestamp = models.DateTimeField(auto_now_add=True)

# class Post(models.Model):
#     CATEGORIES = [
#         ('Crops', 'Crops'), ('Schemes', 'Schemes'), 
#         ('Market', 'Market'), ('Weather', 'Weather')
#     ]
    
#     author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
#     content = models.TextField()
    
#     # Auto-translated fields
#     content_hi = models.TextField(blank=True, null=True) # Hindi
#     content_mr = models.TextField(blank=True, null=True) # Marathi
    
#     category = models.CharField(max_length=50, choices=CATEGORIES, default='Crops')
    
#     # Stores the Cloudinary string URL sent from React
#     image_url = models.URLField(max_length=1000, blank=True, null=True)
    
#     likes_count = models.PositiveIntegerField(default=0)
#     created_at = models.DateTimeField(auto_now_add=True)

#     class Meta:
#         ordering = ['-created_at']

class Post(models.Model):
    CATEGORY_CHOICES = [
        ('PEST_ALERT', 'Pest & Disease Outbreak'),
        ('WEATHER', 'Weather Advisory'),
        ('CROP_ADVICE', 'Crop & Soil Advice'),
        ('MARKET', 'Mandi Rates & Market'),
        ('MACHINERY', 'Equipment & Resource Sharing'),
        ('GENERAL', 'General Discussion'),
    ]

    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='community_posts')
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES, default='GENERAL', db_index=True)
    title = models.CharField(max_length=255)
    content = models.TextField()
    crop_tag = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    
    # Location context for hyper-local filtering
    district = models.CharField(max_length=120, blank=True, null=True, db_index=True)
    latitude = models.FloatField(blank=True, null=True)
    longitude = models.FloatField(blank=True, null=True)
    
    # Media and Urgency flags
    image = models.ImageField(upload_to='community_posts/%Y/%m/', blank=True, null=True)
    # If we accept direct uploads to Cloudinary from the backend, we store the
    # secure URL here. Kept as a separate field to avoid forcing a storage
    # backend change for existing deployments.
    image_url = models.URLField(max_length=1000, blank=True, null=True)
    is_urgent = models.BooleanField(default=False, db_index=True)
    is_verified = models.BooleanField(default=False)
    
    # Denormalized counters for O(1) read performance
    upvotes_count = models.PositiveIntegerField(default=0)
    comments_count = models.PositiveIntegerField(default=0)
    
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_urgent', '-created_at']

    def __str__(self):
        return f"[{self.category}] {self.title} - {self.author}"


class PostComment(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    content = models.TextField()
    is_expert_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-is_expert_verified', 'created_at']


class PostUpvote(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='upvotes')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('post', 'user')


# ──────────────────────────────────────────────────────────────────────
# Async Crop Scan Job
# ──────────────────────────────────────────────────────────────────────
class CropScanJob(models.Model):
    """
    Persists a crop diagnostic scan request so results survive page refreshes.
    The AI pipeline runs inside a Celery background task; the frontend polls
    GET /api/scan/jobs/{id}/ until status reaches COMPLETED or FAILED.
    """

    class Status(models.TextChoices):
        PENDING    = 'PENDING',    'Pending'
        PROCESSING = 'PROCESSING', 'Processing'
        COMPLETED  = 'COMPLETED',  'Completed'
        FAILED     = 'FAILED',     'Failed'

    user       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='scan_jobs')
    status     = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True)

    # User-supplied context
    crop_hint  = models.CharField(max_length=100, blank=True, default='')
    language   = models.CharField(max_length=10, default='en')

    # Raw image stored in DB so the Celery worker can process it without a shared filesystem
    image_data = models.BinaryField()

    # Pipeline output — null until COMPLETED
    result         = models.JSONField(null=True, blank=True)
    error_message  = models.TextField(blank=True, default='')

    created_at   = models.DateTimeField(auto_now_add=True, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"ScanJob #{self.id} [{self.status}] — {self.user}"

# ──────────────────────────────────────────────────────────────────────
# User Notification
# ──────────────────────────────────────────────────────────────────────
class UserNotification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications')
    title = models.CharField(max_length=255)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    link = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Notification for {self.user}: {self.title}"