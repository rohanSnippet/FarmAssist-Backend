import json
import requests
import datetime
from datetime import timedelta
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
from statsmodels.tsa.holtwinters import ExponentialSmoothing
from django.core.cache import cache
from collections import defaultdict

MODEL_PATH = os.path.join(settings.BASE_DIR, 'recommendation/ml_models/crop_recommendation_model.pkl')
try:
    ml_model = joblib.load(MODEL_PATH)
except:
    ml_model = None
   
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
        
class MarketForecastView(APIView):
    permission_classes = [permissions.AllowAny] # Allow all users to see public market data

    def get(self, request):
        commodity = request.GET.get('commodity', 'Mango')
        market = request.GET.get('market', 'Kamthi APMC')
        state = request.GET.get('state', 'Maharashtra')
        
        # 1. Check Cache
        cache_key = f"market_forecast_{state}_{market}_{commodity}".replace(" ", "_")
        cached_data = cache.get(cache_key)
        
        if cached_data:
            return Response({"source": "redis_cache", "data": cached_data}, status=status.HTTP_200_OK)

        # 2. Fetch Live Data
        api_key = getattr(settings, 'DATA_GOV_API_KEY', '')
        url = f"https://api.data.gov.in/resource/35985678-0d79-46b4-9ed6-6f13308a1d24?api-key={api_key}&format=json&filters[Commodity]={commodity}&filters[Market]={market}&filters[State]={state}&limit=30"
        
        try:
            response = requests.get(url, timeout=10)
            api_data = response.json()
            records = api_data.get('records', [])
            
            if not records:
                return Response({"error": "No trading data available."}, status=status.HTTP_404_NOT_FOUND)

            # 3. Process Data
            df = pd.DataFrame(records)
            df['Arrival_Date'] = pd.to_datetime(df['Arrival_Date'], format='%d/%m/%Y')
            df = df.sort_values('Arrival_Date')
            df['Modal_Price'] = pd.to_numeric(df['Modal_Price'])

            # 4. Train ML Model
            model = ExponentialSmoothing(
                df['Modal_Price'].values, 
                trend='add', 
                seasonal=None, 
                initialization_method="estimated"
            )
            fit_model = model.fit()
            forecast = fit_model.forecast(14) # Predict 14 days
            
            # 5. Format for Recharts
            chart_data = []
            last_historical_price = None
            last_date = df['Arrival_Date'].iloc[-1]

            # Parse Historical
            for index, row in df.iterrows():
                last_historical_price = round(row['Modal_Price'])
                chart_data.append({
                    "fullDate": row['Arrival_Date'].strftime('%Y-%m-%d'),
                    "displayDate": row['Arrival_Date'].strftime('%b %d'),
                    "historicalPrice": last_historical_price,
                    "forecastPrice": None
                })
                
            # Tie the lines together
            chart_data[-1]["forecastPrice"] = last_historical_price

            # Parse Forecast
            for i, pred_price in enumerate(forecast):
                future_date = last_date + timedelta(days=i+1)
                chart_data.append({
                    "fullDate": future_date.strftime('%Y-%m-%d'),
                    "displayDate": future_date.strftime('%b %d'),
                    "historicalPrice": None,
                    "forecastPrice": round(pred_price)
                })

            # Cache for 12 hours
            cache.set(cache_key, chart_data, timeout=60 * 60 * 12)

            return Response({"source": "live_api_and_ml", "data": chart_data}, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        

class TopCropsForecastView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        market = request.GET.get('market', 'Kamthi APMC')
        state = request.GET.get('state', 'Maharashtra')
        
        cache_key = f"market_forecast_v3_{state}_{market}".replace(" ", "_")
        cached_data = cache.get(cache_key)
        if cached_data:
            return Response({"source": "redis_cache", "data": cached_data}, status=status.HTTP_200_OK)

        api_key = getattr(settings, 'DATA_GOV_API_KEY', '')
        url = f"https://api.data.gov.in/resource/35985678-0d79-46b4-9ed6-6f13308a1d24?api-key={api_key}&format=json&filters[Market]={market}&filters[State]={state}&limit=800"
        
        try:
            response = requests.get(url, timeout=15)
            records = response.json().get('records', [])
            if not records:
                return Response({"error": "No trading data found for this APMC.", "code": "NO_DATA"}, status=status.HTTP_404_NOT_FOUND)

            df = pd.DataFrame(records)
            df['Arrival_Date'] = pd.to_datetime(df['Arrival_Date'], format='%d/%m/%Y')
            df['Modal_Price'] = pd.to_numeric(df['Modal_Price'])
            
            # Average out duplicate daily entries to prevent 500 crashes
            df = df.groupby(['Commodity', 'Arrival_Date'])['Modal_Price'].mean().reset_index()
            
            # Find crops with enough data points to train an ML model
            latest_prices = df.groupby('Commodity')['Modal_Price'].mean().sort_values(ascending=False)
            valid_crops = [crop for crop in latest_prices.index if len(df[df['Commodity'] == crop]) >= 5]
            
            if not valid_crops:
                return Response({"error": "Insufficient historical data to run AI predictions.", "code": "INSUFFICIENT_DATA"}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

            top_5_commodities = valid_crops[:5]
            global_latest_date = df['Arrival_Date'].max() # The absolute 'Today' anchor
            
            master_dict = {}

            for crop in valid_crops:
                crop_df = df[df['Commodity'] == crop].sort_values('Arrival_Date')
                
                # 1. Train AI Model
                model = ExponentialSmoothing(crop_df['Modal_Price'].values, trend='add', seasonal=None, initialization_method="estimated")
                fit_model = model.fit()
                forecast = fit_model.forecast(14) # Predict 14 days out
                
                last_known_date = crop_df['Arrival_Date'].iloc[-1]
                last_known_price = round(crop_df['Modal_Price'].iloc[-1])

                # 2. Map Actual Historical Data
                for _, row in crop_df.iterrows():
                    date_key = row['Arrival_Date'].strftime('%Y-%m-%d')
                    if date_key not in master_dict:
                        master_dict[date_key] = {"fullDate": date_key, "displayDate": row['Arrival_Date'].strftime('%b %d')}
                    master_dict[date_key][f"{crop}_History"] = round(row['Modal_Price'])

                # 3. CRITICAL: Forward-Fill to the 'Today' Anchor Line
                # This prevents the jagged lines you saw in the image.
                curr_date = last_known_date
                while curr_date < global_latest_date:
                    curr_date += timedelta(days=1)
                    date_key = curr_date.strftime('%Y-%m-%d')
                    if date_key not in master_dict:
                        master_dict[date_key] = {"fullDate": date_key, "displayDate": curr_date.strftime('%b %d')}
                    master_dict[date_key][f"{crop}_History"] = last_known_price # Carry price forward

                # 4. Tie the knot perfectly at 'Today'
                anchor_key = global_latest_date.strftime('%Y-%m-%d')
                if anchor_key not in master_dict:
                    master_dict[anchor_key] = {"fullDate": anchor_key, "displayDate": global_latest_date.strftime('%b %d')}
                master_dict[anchor_key][f"{crop}_Forecast"] = last_known_price

                # 5. Map Future AI Forecast
                for i, pred_price in enumerate(forecast):
                    future_date = global_latest_date + timedelta(days=i+1)
                    date_key = future_date.strftime('%Y-%m-%d')
                    if date_key not in master_dict:
                        master_dict[date_key] = {"fullDate": date_key, "displayDate": future_date.strftime('%b %d')}
                    master_dict[date_key][f"{crop}_Forecast"] = round(max(0, pred_price))

            # Sort chronologically
            final_chart_data = sorted(list(master_dict.values()), key=lambda x: x['fullDate'])

            payload = {
                "top_crops": top_5_commodities,
                "all_crops": valid_crops,
                "chart_data": final_chart_data, 
                "transition_date": global_latest_date.strftime('%b %d')
            }

            cache.set(cache_key, payload, timeout=60 * 60 * 6)
            return Response({"source": "live_api_and_ml", "data": payload}, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({"error": "Failed to process market data.", "details": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
      
      
      
        