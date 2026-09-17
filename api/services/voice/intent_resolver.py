import logging
from typing import Optional, Tuple, List
from api.models import Farm

logger = logging.getLogger(__name__)

def resolve_farm(user, farm_reference: str, ui_farm_id: int = None) -> Tuple[Optional[int], bool, List[dict]]:
    """
    Authoritatively resolves a semantic farm reference to a database ID belonging to the user.
    
    Returns:
        (resolved_farm_id, needs_clarification, list_of_matches)
    """
    if not user:
        return None, False, []

    # Fast path: If no specific reference, use UI context if available
    if not farm_reference or farm_reference.lower() in ['this farm', 'here', 'current farm', 'this']:
        if ui_farm_id:
            # Validate UI context authoritatively
            if Farm.objects.filter(id=ui_farm_id, user=user).exists():
                return ui_farm_id, False, []
        # If UI context is absent but they have exactly 1 farm, assume that one.
        farms = Farm.objects.filter(user=user)
        if farms.count() == 1:
            return farms.first().id, False, []
        return None, True, [] # Clarification needed

    # Match by name or crop (case-insensitive substring)
    farms = Farm.objects.filter(user=user).prefetch_related('seasons')
    matches = []
    
    ref_lower = farm_reference.lower()
    for farm in farms:
        if ref_lower in farm.name.lower():
            matches.append(farm)
            continue
            
        # Check if the reference mentions the crop
        active_season = farm.seasons.filter(is_active=True).first()
        if active_season and ref_lower in active_season.crop_name.lower():
            matches.append(farm)
            continue
            
        # Check district/location
        if user.location_label and ref_lower in user.location_label.lower():
            matches.append(farm)
            continue

    if len(matches) == 1:
        return matches[0].id, False, []
    
    if len(matches) > 1:
        # Ambiguous
        match_data = [{"id": f.id, "name": f.name} for f in matches]
        return None, True, match_data
        
    # No matches found, but check if they only have 1 farm anyway
    if farms.count() == 1:
        return farms.first().id, False, []
        
    return None, True, []
