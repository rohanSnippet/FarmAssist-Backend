from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.contrib.gis.db import models
from django.conf import settings

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
    
class Farm(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='farms')
    name = models.CharField(max_length=255)
    crop_type = models.CharField(max_length=100)
    
    # The PolygonField stores the exact boundaries drawn by the farmer on the React frontend
    boundaries = models.PolygonField()
    
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} - {self.crop_type}"

class PestReport(models.Model):
    farm = models.ForeignKey(Farm, on_delete=models.CASCADE, related_name='pest_reports')
    pest_name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    
    # A PointField to store the exact coordinate where the pest was spotted
    detection_location = models.PointField()
    
    # Track the environmental context at the time of reporting
    temperature_at_report = models.FloatField(null=True, blank=True)
    humidity_at_report = models.FloatField(null=True, blank=True)
    
    reported_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.pest_name} detected at {self.farm.name}"


