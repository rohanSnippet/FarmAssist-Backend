from celery import shared_task
from django.contrib.gis.measure import D
from .models import PestDetection, FarmSeason, PestAlert

@shared_task
def calculate_pest_spread(detection_id):
    try:
        detection = PestDetection.objects.get(id=detection_id)
    except PestDetection.DoesNotExist:
        return
    
    # Base radius for wind-borne spread
    base_radius_km = 10.0
    
    # Query PostGIS for all active seasons within 10km of the detection point
    nearby_seasons = FarmSeason.objects.filter(
        is_active=True,
        farm__boundaries__dwithin=(detection.detection_location, D(km=base_radius_km))
    ).exclude(farm=detection.farm_season.farm)

    alerts_to_create = []
    for season in nearby_seasons:
        # Simple proxy: Alert if growing the same crop
        if season.crop_name.lower() == detection.farm_season.crop_name.lower():
            distance = season.farm.boundaries.distance(detection.detection_location) * 100 
            risk_score = max(0, 100 - (distance * 10))
            
            alerts_to_create.append(PestAlert(
                source_detection=detection,
                target_farm=season.farm,
                risk_score=risk_score
            ))
            
    if alerts_to_create:
        PestAlert.objects.bulk_create(alerts_to_create)