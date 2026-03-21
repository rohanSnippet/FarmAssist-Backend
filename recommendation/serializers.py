# recommendation/serializers.py
from rest_framework import serializers
from .models import CropPrediction

class CropPredictionSerializer(serializers.ModelSerializer):
    class Meta:
        model = CropPrediction
        # We only expose the input fields for the request
        fields = ['nitrogen', 'phosphorus', 'potassium', 'temperature', 'humidity', 'ph', 'rainfall']

class PredictionHistorySerializer(serializers.ModelSerializer):
    # This serializer is for viewing the history later
    class Meta:
        model = CropPrediction
        fields = '__all__'