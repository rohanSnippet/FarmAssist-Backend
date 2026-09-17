import logging
from typing import Dict, Any, List
from django.utils.timezone import now
from api.models import Farm, FarmSeason, CropScanJob

logger = logging.getLogger(__name__)

def get_farmer_context_summary(user) -> Dict[str, Any]:
    """
    Retrieves a lightweight summary of the farmer's active agricultural context.
    This is designed to be injected into the LLM prompt so the LLM can understand
    semantic references (e.g., "my Nashik tomato farm") without having raw database access.
    """
    context_summary = {
        "farmer_name": user.first_name,
        "farms": [],
        "recent_scans": []
    }

    try:
        # Fetch active farms and their current seasons
        farms = Farm.objects.filter(user=user).prefetch_related('seasons')
        for farm in farms:
            active_season = farm.seasons.filter(is_active=True).first()
            farm_data = {
                "farm_name": farm.name,
                "location": {
                    "state": getattr(user, 'state', None),
                    "district": getattr(user, 'location_label', None)
                }
            }
            if active_season:
                crop_age_days = None
                if active_season.planted_date and active_season.planted_date <= now().date():
                    crop_age_days = (now().date() - active_season.planted_date).days
                
                farm_data["active_crop"] = {
                    "crop_name": active_season.crop_name,
                    "crop_age_days": crop_age_days
                }
            else:
                farm_data["active_crop"] = None
                
            context_summary["farms"].append(farm_data)

        # Fetch recent scans (last 3)
        recent_scans = CropScanJob.objects.filter(user=user).order_by('-created_at')[:3]
        for scan in recent_scans:
            scan_data = {
                "scan_job_id": scan.id,
                "status": scan.status,
                "crop_hint": scan.crop_hint,
                "created_at": scan.created_at.isoformat()
            }
            if scan.status == CropScanJob.Status.COMPLETED and scan.result:
                scan_data["diagnosis_summary"] = scan.result.get('primary_diagnosis', 'Unknown')
                
            context_summary["recent_scans"].append(scan_data)
            
    except Exception as e:
        logger.error(f"Error compiling farmer context summary: {e}")
        
    return context_summary
