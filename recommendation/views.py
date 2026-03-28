import json
import requests
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
            
            input_features = pd.DataFrame([{
                'N': data['nitrogen'],
                'P': data['phosphorus'],
                'K': data['potassium'],
                'temperature': data['temperature'],
                'humidity': data['humidity'],
                'ph': data['ph'],
                'rainfall': data['rainfall']
            }])
            
            # --- NEW PROBABILITY LOGIC ---
            # 1. Get the probabilities for all crops
            probabilities = ml_model.predict_proba(input_features)[0]
            
            # 2. Get the corresponding crop names (classes)
            crop_classes = ml_model.classes_
            
            # 3. Create a list of tuples: [('rice', 85.5), ('maize', 12.0), ...]
            crop_probs = []
            for i in range(len(crop_classes)):
                prob_percentage = round(probabilities[i] * 100, 1)
                if prob_percentage > 0: # Only include crops with > 0% chance
                    crop_probs.append({
                        "crop": crop_classes[i],
                        "probability": prob_percentage
                    })
            
            # 4. Sort by highest probability first
            crop_probs = sorted(crop_probs, key=lambda x: x['probability'], reverse=True)
            
            # 5. Get the absolute best match
            top_crop = crop_probs[0]['crop']
            
            # Save to Database (just saving the top crop for history)
            CropPrediction.objects.create(
                user=request.user,
                predicted_crop=top_crop, 
                **data
            )
            
            # Return the top crop AND the top 4 alternatives
            return Response({
                'recommended_crop': top_crop,
                'alternatives': crop_probs[:4] # Returns top 4 highest probability crops
            }, status=status.HTTP_200_OK)
        
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
        # 1. Capture optional coordinates sent from the frontend
        lat = request.data.get('lat')
        lng = request.data.get('lng')

        if not file_obj:
            return Response({"error": "No image provided"}, status=400)

        try:
            client = genai.Client(api_key=settings.GEMINI_API_KEY)
            
            # 1. Update prompt to ask for standardized spelling AND approximate coordinates
            prompt = """
            Analyze this Indian Soil Health Card. 
            Extract the following parameters: Nitrogen (N), Phosphorus (P), Potassium (K), and pH.
            Extract the District or City name mentioned on the card. 
            CRITICAL INSTRUCTIONS FOR LOCATION:
            1. Standardize the location name to its most widely accepted English spelling (e.g., output "Bagalkot" instead of "Bagalkote").
            2. Provide the approximate latitude and longitude for this district/city.
            Return ONLY a valid JSON object. If a value is missing, set it to null.
            Example: {"N": 120, "P": 45, "K": 200, "ph": 6.5, "location_name": "Kullu", "approx_lat": 31.95, "approx_lng": 77.10}
            """

            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=[
                    prompt,
                    types.Part.from_bytes(
                        data=file_obj.read(),
                        mime_type=file_obj.content_type
                    )
                ],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                )
            )
            
            extracted_data = json.loads(response.text)
            
            # 2. Triple-Tiered Location Priority
            final_lat, final_lng = None, None
            card_location = extracted_data.get("location_name")
            gemini_lat = extracted_data.get("approx_lat")
            gemini_lng = extracted_data.get("approx_lng")
            
            # PRIORITY 1: Try Open-Meteo Geocoding (Most accurate)
            if card_location and str(card_location).lower() != "null":
                geo_url = "https://geocoding-api.open-meteo.com/v1/search"
                geo_params = {"name": card_location, "count": 1, "format": "json"}
                try:
                    geo_res = requests.get(geo_url, params=geo_params).json()
                    if geo_res.get("results"):
                        final_lat = geo_res["results"][0]["latitude"]
                        final_lng = geo_res["results"][0]["longitude"]
                        print(f"✅ Geocoded exact location: {card_location} ({final_lat}, {final_lng})")
                    else:
                        print(f"⚠️ Geocoding API missed '{card_location}'.")
                except Exception as e:
                    print(f"❌ Geocoding request failed: {e}")

            # PRIORITY 2: Use Gemini's AI-estimated coordinates (Saves us from spelling errors)
            if not final_lat and gemini_lat and gemini_lng:
                final_lat = gemini_lat
                final_lng = gemini_lng
                print(f"🤖 Fallback to AI coordinates for {card_location}: ({final_lat}, {final_lng})")

            # PRIORITY 3: Device GPS (Absolute last resort)
            if not final_lat and lat and lng:
                final_lat = lat
                final_lng = lng
                print("📡 Fallback to Device GPS coordinates.")

            # 3. Fetch Weather if we secured coordinates
            if final_lat and final_lng:
                weather_url = "https://api.open-meteo.com/v1/forecast"
                weather_params = {
                    "latitude": final_lat,
                    "longitude": final_lng,
                    "current": "temperature_2m,relative_humidity_2m",
                    "daily": "precipitation_sum",
                    "timezone": "auto"
                }
                try:
                    weather_res = requests.get(weather_url, params=weather_params).json()
                    
                    if "current" in weather_res:
                        extracted_data["temperature"] = weather_res["current"].get("temperature_2m")
                        extracted_data["humidity"] = weather_res["current"].get("relative_humidity_2m")
                    
                    if "daily" in weather_res and weather_res["daily"].get("precipitation_sum"):
                        extracted_data["rainfall"] = weather_res["daily"]["precipitation_sum"][0]
                        
                    print(f"🌤️ Weather fetched for ({final_lat}, {final_lng}) - Humidity: {extracted_data.get('humidity')}%")
                except Exception as e:
                    print(f"❌ Weather fetching failed: {e}")

            # Clean up the output so frontend doesn't get unnecessary data
            extracted_data.pop("approx_lat", None)
            extracted_data.pop("approx_lng", None)

            return Response(extracted_data, status=200)

        except Exception as e:
            return Response({"error": str(e)}, status=500)