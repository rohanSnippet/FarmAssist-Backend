import json
import logging
from django.core.exceptions import ValidationError
from .models import ChemicalExtractionDraft, AuthorityTier

logger = logging.getLogger(__name__)

INDIAN_REGION_TAGS = [
    'india', 'indian', 'icar', 'cibrc', 'tnau', 'mpkv', 'pdkv', 
    'maharashtra', 'karnataka', 'tamil nadu', 'andhra pradesh', 
    'telangana', 'gujarat', 'punjab', 'haryana', 'uttar pradesh',
    'madhya pradesh', 'bihar', 'west bengal', 'odisha'
]

def validate_india_centric_source(draft: ChemicalExtractionDraft):
    """
    Validates that the source of the draft is an accepted Indian authority.
    Rejects sources from USDA, EPA, etc.
    """
    source_org = draft.document.source.organization.lower()
    
    # 1. Check Authority Tier (Tier 1 is CIB&RC)
    if draft.document.source.authority_tier == AuthorityTier.TIER_1:
        return True
        
    # 2. Check for explicit Indian organizations
    is_indian = any(tag in source_org for tag in INDIAN_REGION_TAGS)
    
    # Check document title for Indian context
    doc_title = draft.document.title.lower()
    is_indian_doc = any(tag in doc_title for tag in INDIAN_REGION_TAGS)
    
    if not (is_indian or is_indian_doc):
        # We reject non-Indian sources for this KB.
        raise ValidationError(
            f"Source '{draft.document.source.organization}' does not appear to be an authorized Indian agricultural source. "
            f"Only CIB&RC, ICAR, and State Universities are allowed."
        )

def validate_draft_for_approval(draft: ChemicalExtractionDraft):
    """
    Called before a ChemicalExtractionDraft can be moved to APPROVED status.
    """
    logger.info(f"[Validator] Validating draft {draft.id}")
    
    # 1. Enforce India-only constraint
    validate_india_centric_source(draft)
    
    # 2. Validate JSON structure
    try:
        data = draft.extracted_json
        if isinstance(data, str):
            data = json.loads(data)
    except json.JSONDecodeError:
        raise ValidationError("Extracted data is not valid JSON.")
        
    required_keys = ['active_ingredient', 'dose_per_hectare_min', 'dose_unit']
    for key in required_keys:
        if key not in data or not data[key]:
            raise ValidationError(f"Missing mandatory field in extraction: {key}")
            
    # Check for unit compliance (India typically uses ml/acre, g/acre, ml/ha, g/ha, kg/ha)
    valid_units = ['ml', 'g', 'kg', 'l', 'ml/ha', 'g/ha', 'kg/ha', 'l/ha', 'ml/acre', 'g/acre']
    if data['dose_unit'].lower() not in valid_units:
        raise ValidationError(f"Invalid dose unit '{data['dose_unit']}'. Must be SI or standard Indian agricultural units.")

    return True
