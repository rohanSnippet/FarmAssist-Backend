# recommendation/views.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from .serializers import CropPredictionSerializer, PredictionHistorySerializer
from .models import CropPrediction
import joblib
import os
from django.conf import settings
import pandas as pd

# Load model logic (same as before)
MODEL_PATH = os.path.join(settings.BASE_DIR, 'recommendation/ml_models/crop_recommendation_model.pkl')
try:
    ml_model = joblib.load(MODEL_PATH)
except:
    ml_model = None

class RecommendCropView(APIView):
    # Ensure only logged-in users can access this
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if ml_model is None:
            return Response({'error': 'ML Model not loaded'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        serializer = CropPredictionSerializer(data=request.data)
        
        if serializer.is_valid():
            # 1. Prepare data for the ML model
            data = serializer.validated_data
            input_features = [[
                data['nitrogen'],
                data['phosphorus'],
                data['potassium'],
                data['temperature'],
                data['humidity'],
                data['ph'],
                data['rainfall']
            ]]
            
            """ input_features = pd.DataFrame([{
                'nitrogen': data['nitrogen'],
                'phosphorus': data['phosphorus'],
                'potassium': data['potassium'],
                'temperature': data['temperature'],
                'humidity': data['humidity'],
                'ph': data['ph'],
                'rainfall': data['rainfall']
            }]) """
            
            # 2. Make Prediction
            prediction = ml_model.predict(input_features)
            result = prediction[0]
            
            # 3. Save to Database (History)
            # We explicitly pass the user and the calculated result
            CropPrediction.objects.create(
                user=request.user,
                predicted_crop=result,
                **data
            )
            
            return Response({'recommended_crop': result}, status=status.HTTP_200_OK)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class UserHistoryView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        # Fetch predictions only for the current user
        history = CropPrediction.objects.filter(user=request.user).order_by('-created_at')
        serializer = PredictionHistorySerializer(history, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)