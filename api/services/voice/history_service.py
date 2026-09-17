import logging
from typing import Dict, Any
from api.models import CropScanJob, PestDetection

logger = logging.getLogger(__name__)

def get_farmer_history_summary(user, farm_id=None, farm_season_id=None) -> Dict[str, Any]:
    """
    Retrieves relevant historical information for the farmer.
    Optionally scoped to a specific farm or crop season.
    """
    history = {
        "recent_scans": [],
        "recent_detections": []
    }
    
    try:
        # 1. Fetch recent scans
        scans_query = CropScanJob.objects.filter(user=user, status=CropScanJob.Status.COMPLETED)
        if farm_season_id:
            scans_query = scans_query.filter(farm_season_id=farm_season_id)
            
        recent_scans = scans_query.order_by('-completed_at')[:3]
        for scan in recent_scans:
            scan_data = {
                "scan_id": scan.id,
                "crop": scan.crop_hint or "Unknown",
                "diagnosis": scan.result.get('primary_diagnosis', 'Unknown') if scan.result else "Unknown",
                "completed_at": scan.completed_at.isoformat() if scan.completed_at else None
            }
            history["recent_scans"].append(scan_data)
            
        # 2. Fetch recent pest/disease detections
        if farm_season_id:
            detections = PestDetection.objects.filter(farm_season_id=farm_season_id).order_by('-timestamp')[:3]
        elif farm_id:
            detections = PestDetection.objects.filter(farm_season__farm_id=farm_id).order_by('-timestamp')[:5]
        else:
            detections = PestDetection.objects.filter(farm_season__farm__user=user).order_by('-timestamp')[:5]
            
        for d in detections:
            history["recent_detections"].append({
                "detection_id": d.id,
                "pest_or_disease": d.pest_name,
                "severity": d.severity_level,
                "farm": d.farm_season.farm.name,
                "crop": d.farm_season.crop_name,
                "timestamp": d.timestamp.isoformat()
            })
            
    except Exception as e:
        logger.error(f"Error retrieving history for user {user.id}: {e}")
        
    return history
