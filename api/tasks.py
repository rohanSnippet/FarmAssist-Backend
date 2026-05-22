from celery import shared_task
from .models import PestDetection, FarmSeason, PestAlertBroadcast
from django.contrib.gis.measure import D

@shared_task
def calculate_pest_spread(detection_id):
    try:
        detection = PestDetection.objects.get(id=detection_id)
    except PestDetection.DoesNotExist:
        print("❌ Detection not found.")
        return
    
    base_radius_km = 10.0
    wind_speed_kmh = detection.weather_snapshot.get('wind_speed', 0)
    dynamic_radius_km = 10.0 + (wind_speed_kmh / 5.0)
    dynamic_radius_m = dynamic_radius_km * 1000.0 # Convert to meters for math
    
    source_crop = detection.farm_season.crop_name.strip().lower()

    print(f"\n=======================================================")
    print(f"📡 ALERT BROADCAST TRIGGERED FROM: '{detection.farm_season.farm.name}'")
    print(f"🌾 SOURCE CROP: '{source_crop}'")
    print(f"=======================================================\n")

    # --- X-RAY VISION: LOOK AT EVERY ACTIVE CROP IN THE DATABASE ---
    all_active_seasons = FarmSeason.objects.filter(is_active=True).exclude(farm=detection.farm_season.farm)
    
    print(f"🔍 System found {all_active_seasons.count()} OTHER active farms globally.")
    
    for s in all_active_seasons:
        # 1. Spherical distance returns METERS! Divide by 1000 for KM.
        dist_m = s.farm.boundaries.distance(detection.detection_location)
        dist_km = dist_m / 1000.0 
        
        target_crop = s.crop_name.strip().lower()
        
        print(f"   -> Analyzing Farm: '{s.farm.name}'")
        print(f"      📍 Distance: {dist_km:.2f} km away (Needs to be < {dynamic_radius_km:.2f}km)")
        print(f"      🌱 Crop: '{target_crop}' (Needs to match '{source_crop}')")
        
        if dist_km <= dynamic_radius_km and target_crop == source_crop:
            print(f"      ✅ PERFECT MATCH! Alerting this farm.")
        elif dist_km > dynamic_radius_km:
            print(f"      ❌ FAILED: Too far away.")
        elif target_crop != source_crop:
            print(f"      ❌ FAILED: Crop mismatch.")
        print("   --------------------------------------")

    nearby_seasons = FarmSeason.objects.filter(
        is_active=True,
        farm__boundaries__dwithin=(detection.detection_location, D(km=dynamic_radius_km))
    ).exclude(farm=detection.farm_season.farm)

    affected_user_ids = set()
    max_risk_overall = 0.0

    # 1. Collect all affected users and find the highest risk
    for season in nearby_seasons:
        distance_m = season.farm.boundaries.distance(detection.detection_location) 
        risk = 100 - ((distance_m / dynamic_radius_m) * 100)
        
        affected_user_ids.add(season.farm.user.id)
        max_risk_overall = max(max_risk_overall, risk)

    # 2. Fire and Forget: Save ONE compressed row
    if affected_user_ids:
        PestAlertBroadcast.objects.create(
            source_detection=detection,
            max_risk_score=round(max(0.0, min(100.0, max_risk_overall)), 1),
            notified_users=list(affected_user_ids) # Store as JSON array
        )
        print(f"\n🚀 SUCCESS: Broadcasted ONE alert to {len(affected_user_ids)} users!")