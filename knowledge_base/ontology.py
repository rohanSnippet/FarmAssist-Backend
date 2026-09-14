import logging
from django.db.models import Q
from .models import DiagnosisAlias, CropDiagnosis, Crop, Pathogen

logger = logging.getLogger(__name__)

def resolve_ml_prediction(crop_name: str, prediction_name: str) -> CropDiagnosis:
    """
    Resolves an ML string prediction (e.g. 'Early_Blight_Tomato', 'Fall Armyworm') 
    into a canonical CropDiagnosis strictly for the Indian context.
    """
    logger.info(f"[Ontology] Resolving prediction: '{prediction_name}' for crop: '{crop_name}'")
    
    # 1. Try to match an exact alias first
    alias_match = DiagnosisAlias.objects.filter(
        alias__iexact=prediction_name
    ).select_related('canonical_diagnosis', 'canonical_diagnosis__crop', 'canonical_diagnosis__pathogen').first()

    if alias_match:
        # Verify crop context matches if crop is provided
        if crop_name and alias_match.canonical_diagnosis.crop.name.lower() != crop_name.lower():
            logger.warning(
                f"[Ontology] Alias match found, but crop mismatch: "
                f"Expected {alias_match.canonical_diagnosis.crop.name}, got {crop_name}"
            )
            # We strictly enforce crop context for Indian agriculture
            return None
        
        return alias_match.canonical_diagnosis

    # 2. Fallback: Fuzzy or partial match against canonical Pathogen/Crop
    if crop_name:
        try:
            possible_diagnoses = CropDiagnosis.objects.filter(
                Q(diagnosis_name__icontains=prediction_name) | 
                Q(pathogen__canonical_name__icontains=prediction_name) |
                Q(pathogen__scientific_name__icontains=prediction_name),
                crop__name__iexact=crop_name
            ).first()
            
            if possible_diagnoses:
                logger.info(f"[Ontology] Resolved via partial match to {possible_diagnoses}")
                return possible_diagnoses
        except Exception as e:
            logger.error(f"[Ontology] Error resolving partial match: {e}")

    logger.warning(f"[Ontology] Unresolved diagnosis: '{prediction_name}' for crop '{crop_name}'")
    return None
