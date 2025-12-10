# recommendation/models.py
from django.db import models
from django.conf import settings  # To refer to the User model

class CropPrediction(models.Model):
    # Link to the user who made the prediction
    # on_delete=models.CASCADE means if user is deleted, their history is deleted
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='predictions')
    
    # Input Features
    nitrogen = models.FloatField()
    phosphorus = models.FloatField()
    potassium = models.FloatField()
    temperature = models.FloatField()
    humidity = models.FloatField()
    ph = models.FloatField()
    rainfall = models.FloatField()
    
    # The Result
    predicted_crop = models.CharField(max_length=100)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.predicted_crop} - {self.created_at.strftime('%Y-%m-%d')}"