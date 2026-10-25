import logging
from typing import Dict, Any, List
from django.utils.timezone import now
from api.models import Farm, FarmSeason, CropScanJob

logger = logging.getLogger(__name__)

def get_farmer_context_summary(user) -> Dict[str, Any]:
    """
    Retrieves a lightweight summary of the farmer's active agricultural context.
    This is designed to be injected into the LLM prompt or LiveKit JWT metadata so the LLM
    can understand semantic references (e.g., "my Nashik tomato farm", "my recent leaf scan")
    without raw database queries or leaking data between farmers.
    """
    if not user or not getattr(user, 'is_authenticated', False):
        return {
            "farmer_name": "Farmer",
            "user_id": None,
            "district": "",
            "farms": [],
            "recent_scans": []
        }

    context_summary = {
        "farmer_name": getattr(user, 'first_name', None) or "Farmer",
        "user_id": user.id,
        "district": getattr(user, 'location_label', '') or '',
        "farms": [],
        "recent_scans": []
    }

    try:
        # Fetch active farms and their current seasons
        farms = Farm.objects.filter(user=user).prefetch_related('seasons')
        for farm in farms:
            active_season = farm.seasons.filter(is_active=True).first()
            farm_data = {
                "farm_id": farm.id,
                "farm_name": farm.name,
                "location": {
                    "district": getattr(user, 'location_label', '') or ''
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
                "crop_hint": scan.crop_hint or "Crop",
                "created_at": scan.created_at.strftime('%Y-%m-%d')
            }
            if scan.status == CropScanJob.Status.COMPLETED and scan.result:
                scan_data["diagnosis"] = scan.result.get('primary_diagnosis', 'Healthy / Unknown')
                conf = scan.result.get('confidence', 0)
                scan_data["confidence_pct"] = int(conf * 100) if conf <= 1 else int(conf)
                # Extract first practical treatment if available
                practices = scan.result.get('management_practices') or scan.result.get('recommendations')
                if isinstance(practices, list) and len(practices) > 0:
                    first_p = practices[0]
                    desc = first_p.get('description') if isinstance(first_p, dict) else str(first_p)
                    scan_data["treatment_hint"] = desc[:120]
                elif isinstance(practices, dict):
                    scan_data["treatment_hint"] = str(list(practices.values())[0])[:120]
                
            context_summary["recent_scans"].append(scan_data)
            
    except Exception as e:
        logger.error(f"Error compiling farmer context summary: {e}")
        
    return context_summary
