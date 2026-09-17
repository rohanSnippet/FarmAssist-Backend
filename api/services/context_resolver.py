from dataclasses import dataclass
from typing import Optional
from datetime import date
from django.utils.timezone import now
from api.models import FarmSeason, Farm

@dataclass(frozen=True)
class GrowthStageInfo:
    stage_name: Optional[str]
    source: str  # CONFIRMED, OBSERVED, AGE_ESTIMATED, UNKNOWN
    confidence: float
    is_confirmed: bool

@dataclass(frozen=True)
class LocationInfo:
    state: Optional[str]
    district: Optional[str]

@dataclass(frozen=True)
class AgriculturalContext:
    farmer_id: int
    farm_id: Optional[int]
    farm_season_id: Optional[int]
    crop_name: str
    planting_date: Optional[date]
    crop_age_days: Optional[int]
    growth_stage: GrowthStageInfo
    location: LocationInfo
    schema_version: int = 1

def resolve_context(user, farm_id=None, farm_season_id=None) -> AgriculturalContext:
    """
    Resolves the AgriculturalContext for a given user and optional farm/season.
    Precedence for GrowthStage: CONFIRMED > OBSERVED > AGE_ESTIMATED > UNKNOWN.
    """
    farm = None
    farm_season = None
    
    # 1. Resolve Farm and Season
    if farm_season_id:
        farm_season = FarmSeason.objects.filter(id=farm_season_id, farm__user=user).select_related('farm').first()
        if farm_season:
            farm = farm_season.farm
    elif farm_id:
        farm = Farm.objects.filter(id=farm_id, user=user).first()
        if farm:
            farm_season = FarmSeason.objects.filter(farm=farm, is_active=True).first()
    
    # Defaults
    crop_name = "Unknown"
    planting_date = None
    crop_age_days = None
    location_info = LocationInfo(
        state=getattr(user, 'state', None),
        district=getattr(user, 'location_label', None)
    )
    
    stage_name = None
    stage_source = "UNKNOWN"
    is_confirmed = False
    
    if farm_season:
        crop_name = farm_season.crop_name
        planting_date = farm_season.planted_date
        
        # Calculate Crop Age
        if planting_date and planting_date <= now().date():
            crop_age_days = (now().date() - planting_date).days
            
            # Age-Estimated Stage Fallback
            # Find the stage profile where age falls in [expected_age_min_days, expected_age_max_days]
            try:
                from knowledge_base.models import CropStageProfile
                profiles = CropStageProfile.objects.filter(
                    crop__name__iexact=crop_name,
                    expected_age_min_days__lte=crop_age_days,
                    expected_age_max_days__gte=crop_age_days
                ).select_related('growth_stage')
                
                if profiles.exists():
                    stage_name = profiles.first().growth_stage.name
                    stage_source = "AGE_ESTIMATED"
            except Exception:
                pass

    growth_stage_info = GrowthStageInfo(
        stage_name=stage_name,
        source=stage_source,
        confidence=1.0 if is_confirmed else 0.7,
        is_confirmed=is_confirmed
    )
    
    return AgriculturalContext(
        farmer_id=user.id,
        farm_id=farm.id if farm else None,
        farm_season_id=farm_season.id if farm_season else None,
        crop_name=crop_name,
        planting_date=planting_date,
        crop_age_days=crop_age_days,
        growth_stage=growth_stage_info,
        location=location_info
    )
