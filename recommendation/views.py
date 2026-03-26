import json
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from rest_framework.parsers import MultiPartParser, FormParser
from .serializers import CropPredictionSerializer, PredictionHistorySerializer
from .models import CropPrediction
import joblib
import os
from django.conf import settings
import pandas as pd
from google import genai
from google.genai import types

MODEL_PATH = os.path.join(settings.BASE_DIR, 'recommendation/ml_models/crop_recommendation_model.pkl')
try:
    ml_model = joblib.load(MODEL_PATH)
except:
    ml_model = None
    
""" class RecommendCropView(APIView):
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
             //put 3 double quoted here
             input_features = pd.DataFrame([{
                'nitrogen': data['nitrogen'],
                'phosphorus': data['phosphorus'],
                'potassium': data['potassium'],
                'temperature': data['temperature'],
                'humidity': data['humidity'],
                'ph': data['ph'],
                'rainfall': data['rainfall']
            }]) //put 3 double quotes here
            
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
 """

class RecommendCropView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if ml_model is None:
            return Response({'error': 'ML Model not loaded'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        serializer = CropPredictionSerializer(data=request.data)
        
        if serializer.is_valid():
            data = serializer.validated_data
            
            # 1. Prepare data as a DataFrame with the EXACT column names 
            # used in your Crop_recommendation.csv
            # (Double-check your CSV to ensure these names match exactly)
            input_features = pd.DataFrame([{
                'N': data['nitrogen'],           # Changed from 'nitrogen' to 'N' if that's what's in the CSV
                'P': data['phosphorus'],         # Changed from 'phosphorus' to 'P'
                'K': data['potassium'],          # Changed from 'potassium' to 'K'
                'temperature': data['temperature'],
                'humidity': data['humidity'],
                'ph': data['ph'],
                'rainfall': data['rainfall']
            }])
            
            # 2. Make Prediction
            prediction = ml_model.predict(input_features)
            result = prediction[0]
            
            # 3. Save to Database
            # (Assuming your CropPrediction model uses 'recommended_crop' instead of 'predicted_crop')
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
    
class SoilCardOCRView(APIView):
    parser_classes = (MultiPartParser, FormParser)

    def post(self, request, *args, **kwargs):
        file_obj = request.FILES.get('image')
        if not file_obj:
            return Response({"error": "No image provided"}, status=400)

        try:
            # 2. Initialize the client INSIDE the view using the new SDK
            client = genai.Client(api_key=settings.GEMINI_API_KEY)
            
            prompt = """
            Analyze this Indian Soil Health Card. 
            Extract the following parameters: Nitrogen (N), Phosphorus (P), Potassium (K), and pH.
            If the card is in a regional language, translate the field names internally and extract the numerical values.
            If any of temperature, humidity, rainfall details is missing, fetch them using live data from the location given in the soil health card.  
            Return ONLY a valid JSON object with the keys 'N', 'P', 'K', 'temperature', 'humidity', 'ph' and 'rainfall'. 
            Do not include markdown blocks or any other text. 
            Example: {"N": 120, "P": 45, "K": 200, "ph": 6.5, "temperature": 34.8, "humidity": 23, "rainfall": 20}
            """

            # 3. Use the new syntax for generating content from bytes
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=[
                    prompt,
                    types.Part.from_bytes(
                        data=file_obj.read(),
                        mime_type=file_obj.content_type
                    )
                ]
            )
            
            # Parse the JSON string returned by the model
            raw_text = response.text.strip().replace("```json", "").replace("```", "")
            extracted_data = json.loads(raw_text)

            return Response(extracted_data, status=200)

        except Exception as e:
            return Response({"error": str(e)}, status=500)