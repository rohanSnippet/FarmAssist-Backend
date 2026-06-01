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
from .crop_registry import get_allowed_crops

MODEL_PATH = os.path.join(settings.BASE_DIR, 'recommendation/ml_models/crop_recommendation_model2.pkl')
try:
    ml_model = joblib.load(MODEL_PATH)
except:
    ml_model = None
    
def normalize_soil_data(raw_n, raw_p, raw_k, raw_rainfall):
    # Absolute maximums derived from Crop_recommendation.csv
    DATASET_MAX_N = 140.0
    DATASET_MAX_P = 145.0
    DATASET_MAX_K = 205.0
    DATASET_MAX_RAIN = 298.5
    
    # 1. Cap NPK values to prevent Out-Of-Distribution (OOD) errors.
    norm_n = min(float(raw_n), DATASET_MAX_N)
    norm_p = min(float(raw_p), DATASET_MAX_P)
    norm_k = min(float(raw_k), DATASET_MAX_K)
    
    # 2. Rainfall Safety Net
    norm_rainfall = float(raw_rainfall)
    # If the API or user provides total annual rainfall (e.g., 1200mm), 
    # we approximate the monthly average by dividing by 4.
    if norm_rainfall > DATASET_MAX_RAIN:
        norm_rainfall = norm_rainfall / 4.0
        # If it's still too high, cap it at the model's absolute limit
        norm_rainfall = min(norm_rainfall, DATASET_MAX_RAIN)
        
    return norm_n, norm_p, norm_k, norm_rainfall

# --- ADD THIS DICTIONARY DIRECTLY IN VIEWS.PY ---
# This is our "Hardcoded AI Agronomist". It strictly controls what crops are allowed in which states.
STATE_CROP_WHITELIST = {
    "andhra pradesh": ["rice", "maize", "chickpea", "kidneybeans", "pigeonpeas", "mothbeans", "mungbean", "blackgram", "lentil", "pomegranate", "banana", "mango", "grapes", "watermelon", "muskmelon", "orange", "papaya", "cotton"],
    "telangana": ["rice", "maize", "chickpea", "kidneybeans", "pigeonpeas", "mothbeans", "mungbean", "blackgram", "lentil", "pomegranate", "banana", "mango", "grapes", "watermelon", "muskmelon", "orange", "papaya", "cotton"],
    "maharashtra": ["rice", "maize", "chickpea", "kidneybeans", "pigeonpeas", "mothbeans", "mungbean", "blackgram", "lentil", "pomegranate", "banana", "mango", "grapes", "watermelon", "muskmelon", "orange", "papaya", "cotton", "coffee", "jute"],
    "karnataka": ["rice", "maize", "chickpea", "kidneybeans", "pigeonpeas", "mothbeans", "mungbean", "blackgram", "lentil", "pomegranate", "banana", "mango", "grapes", "watermelon", "muskmelon", "orange", "papaya", "cotton", "coffee", "coconut"],
    "Himachal Pradesh": ["maize", "kidneybeans", "pomegranate", "mango", "grapes", "apple", "orange"],
    "uttarakhand": ["maize", "kidneybeans", "pomegranate", "mango", "grapes", "apple", "orange", "rice"],
    "jammu and kashmir": ["maize", "kidneybeans", "pomegranate", "apple", "orange"],
    "kerala": ["rice", "banana", "mango", "papaya", "coconut", "coffee", "jute"],
    "gujarat": ["rice", "maize", "chickpea", "kidneybeans", "pigeonpeas", "mothbeans", "mungbean", "blackgram", "lentil", "pomegranate", "banana", "mango", "grapes", "watermelon", "muskmelon", "orange", "papaya", "cotton"],
    "punjab": ["rice", "maize", "chickpea", "kidneybeans", "pigeonpeas", "mothbeans", "mungbean", "blackgram", "lentil", "pomegranate", "banana", "mango", "grapes", "watermelon", "muskmelon", "orange", "papaya", "cotton"],
    "tamil nadu": ["rice", "maize", "chickpea", "kidneybeans", "pigeonpeas", "mothbeans", "mungbean", "blackgram", "lentil", "pomegranate", "banana", "mango", "grapes", "watermelon", "muskmelon", "orange", "papaya", "cotton", "coconut", "coffee"],
    "madhya pradesh": ["rice", "maize", "chickpea", "kidneybeans", "pigeonpeas", "mothbeans", "mungbean", "blackgram", "lentil", "pomegranate", "banana", "mango", "grapes", "watermelon", "muskmelon", "orange", "papaya", "cotton"]
}

def get_allowed_crops(state_name):
    """Helper function to fetch the allowed crops safely."""
    if not state_name:
        return None
    state_name = str(state_name).lower().strip()
    return STATE_CROP_WHITELIST.get(state_name, None)

class RecommendCropView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if ml_model is None:
            return Response({'error': 'ML Model not loaded'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        serializer = CropPredictionSerializer(data=request.data)
        
        if serializer.is_valid():
            data = serializer.validated_data
            
            # 1. Normalize data safely
            safe_n, safe_p, safe_k, safe_rain = normalize_soil_data(
                data['nitrogen'], data['phosphorus'], data['potassium'], data['rainfall']
            )
                        
            input_features = pd.DataFrame([{
                'N': safe_n,
                'P': safe_p,
                'K': safe_k,
                'temperature': data['temperature'],
                'humidity': data['humidity'],
                'ph': data['ph'],
                'rainfall': safe_rain
            }]).astype(dtype='float64')
            
            # 2. Get ML Probabilities
            probabilities = ml_model.predict_proba(input_features)[0]
            crop_classes = ml_model.classes_
            
            crop_probs = []
            for i in range(len(crop_classes)):
                prob_percentage = round(probabilities[i] * 100, 1)
                if prob_percentage > 0:
                    crop_probs.append({
                        "crop": crop_classes[i],
                        "probability": prob_percentage
                    })
            
            crop_probs = sorted(crop_probs, key=lambda x: x['probability'], reverse=True)
            
            # 3. Apply Geographical Safety Filter
            user_state = request.data.get("state", "")
            allowed_crops = get_allowed_crops(user_state)

            if allowed_crops is not None:
                # Filter out crops that are NOT in the state's whitelist
                final_safe_crops = [
                    crop for crop in crop_probs if crop["crop"] in allowed_crops
                ]

                # If the whitelist rejected everything (very rare), just fallback to ML
                if len(final_safe_crops) == 0:
                    final_safe_crops = crop_probs[:5]
            else:
                # If the user didn't provide a state, or we don't have rules for it, trust the ML
                final_safe_crops = crop_probs[:5]

            # 4. Save and Return the Final Safe Crop
            top_crop = final_safe_crops[0]['crop']
                        
            CropPrediction.objects.create(
                user=request.user,
                predicted_crop=top_crop, 
                **data
            )
            
            # Return top crop, and up to 4 alternatives (ensuring no indexing errors)
            return Response({
                'recommended_crop': top_crop,
                'alternatives': final_safe_crops[1:5] 
            }, status=status.HTTP_200_OK)
            
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
class UserHistoryView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        history = CropPrediction.objects.filter(user=request.user).order_by('-created_at')
        serializer = PredictionHistorySerializer(history, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

class SoilCardOCRView(APIView):
    parser_classes = (MultiPartParser, FormParser)

    def post(self, request, *args, **kwargs):
        file_obj = request.FILES.get('image')
        lat = request.data.get('lat')
        lng = request.data.get('lng')

        if not file_obj:
            return Response({"error": "No image provided"}, status=400)

        try:
            client = genai.Client(api_key=settings.GEMINI_API_KEY)
            
            # UPGRADE 1: Explicitly ask Gemini for the State
            prompt = """
            Analyze this Indian Soil Health Card. 
            Extract the following parameters: Nitrogen (N), Phosphorus (P), Potassium (K), and pH.
            Extract the District or City name mentioned on the card. 
            Extract or Infer the State name where this district is located in India.
            
            CRITICAL INSTRUCTIONS FOR LOCATION & CLIMATE:
            1. Standardize the location name to its most widely accepted English spelling.
            2. Provide the approximate latitude and longitude for this district/city.
            3. Based on your climate knowledge database for this district, provide the average long-term cumulative monthly rainfall baseline (in mm) for the current agricultural growing season in this region.
            Return ONLY a valid JSON object. If a value is missing, set it to null.
            Example: {"N": 120, "P": 45, "K": 200, "ph": 6.5, "location_name": "Kullu", "state": "Himachal Pradesh", "approx_lat": 31.95, "approx_lng": 77.10, "estimated_seasonal_rainfall": 85.0}
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
            
            final_lat, final_lng = None, None
            card_location = extracted_data.get("location_name")
            gemini_lat = extracted_data.get("approx_lat")
            gemini_lng = extracted_data.get("approx_lng")
            
            if card_location and str(card_location).lower() != "null":
                geo_url = "https://geocoding-api.open-meteo.com/v1/search"
                geo_params = {"name": card_location, "count": 1, "format": "json"}
                try:
                    geo_res = requests.get(geo_url, params=geo_params).json()
                    if geo_res.get("results"):
                        final_lat = geo_res["results"][0]["latitude"]
                        final_lng = geo_res["results"][0]["longitude"]
                        
                        # UPGRADE 2: Use Geocoding API to lock in the State (admin1)
                        # If Gemini failed to guess the state, Open-Meteo will provide it exactly!
                        fetched_state = geo_res["results"][0].get("admin1")
                        if fetched_state:
                            extracted_data["state"] = fetched_state
                            
                        print(f"✅ Geocoded exact location: {card_location}, {extracted_data.get('state')} ({final_lat}, {final_lng})")
                except Exception as e:
                    print(f"❌ Geocoding request failed: {e}")

            if not final_lat and gemini_lat and gemini_lng:
                final_lat = gemini_lat
                final_lng = gemini_lng
                print(f"🤖 Fallback to AI coordinates for {card_location}: ({final_lat}, {final_lng})")

            if not final_lat and lat and lng:
                final_lat = lat
                final_lng = lng
                print("📡 Fallback to Device GPS coordinates.")

            if final_lat and final_lng:
                today = datetime.date.today()
                start_date = (today - timedelta(days=95)).strftime("%Y-%m-%d")
                end_date = (today - timedelta(days=5)).strftime("%Y-%m-%d")
                
                current_weather_url = "https://api.open-meteo.com/v1/forecast"
                current_params = {
                    "latitude": final_lat,
                    "longitude": final_lng,
                    "current": "temperature_2m,relative_humidity_2m",
                    "timezone": "auto"
                }
                
                archive_weather_url = "https://archive-api.open-meteo.com/v1/archive"
                archive_params = {
                    "latitude": final_lat,
                    "longitude": final_lng,
                    "start_date": start_date,
                    "end_date": end_date,
                    "daily": "precipitation_sum",
                    "timezone": "auto"
                }
                
                try:
                    curr_res = requests.get(current_weather_url, params=current_params).json()
                    if "current" in curr_res:
                        extracted_data["temperature"] = curr_res["current"].get("temperature_2m")
                        extracted_data["humidity"] = curr_res["current"].get("relative_humidity_2m")
                    
                    arch_res = requests.get(archive_weather_url, params=archive_params).json()
                    
                    if "daily" in arch_res and "precipitation_sum" in arch_res["daily"]:
                        rain_data = [r for r in arch_res["daily"]["precipitation_sum"] if r is not None]
                        if rain_data:
                            seasonal_rainfall = sum(rain_data) / 3.0
                            extracted_data["rainfall"] = round(seasonal_rainfall, 2)
                    
                    if extracted_data.get("rainfall", 0) <= 5.0 and "estimated_seasonal_rainfall" in extracted_data:
                        print("⚠️ Low/Zero recent rainfall detected. Falling back to AI Climatology baseline.")
                        extracted_data["rainfall"] = extracted_data["estimated_seasonal_rainfall"]
                        
                    print(f"🌤️ Weather processed - Temp: {extracted_data.get('temperature')}°C, Rain: {extracted_data.get('rainfall')}mm")
                except Exception as e:
                    print(f"❌ Weather fetching failed: {e}")
                    if "estimated_seasonal_rainfall" in extracted_data:
                        extracted_data["rainfall"] = extracted_data["estimated_seasonal_rainfall"]

            # Clean up the output
            extracted_data.pop("approx_lat", None)
            extracted_data.pop("approx_lng", None)
            extracted_data.pop("estimated_seasonal_rainfall", None)

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
      
      
      
        