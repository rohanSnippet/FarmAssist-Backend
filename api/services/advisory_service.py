import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

def build_structured_advisory(
    diagnosis: Dict[str, Any], 
    context_dict: Dict[str, Any], 
    treatments: List[Dict[str, Any]],
    practices: Dict[str, List[str]]
) -> Dict[str, Any]:
    """
    Builds the authoritative structured data advisory that Gemini will translate.
    Follows the strict schema contract.
    """
    
    growth_stage = context_dict.get("growth_stage", {})
    location = context_dict.get("location", {})
    
    structured = {
        "schema_version": 1,
        "agricultural_context": {
            "farm_id": context_dict.get("farm_id"),
            "crop": context_dict.get("crop_name"),
            "crop_age_days": context_dict.get("crop_age_days"),
            "location_state": location.get("state"),
            "location_district": location.get("district")
        },
        "diagnosis": {
            "condition": diagnosis.get("condition_type", "unknown"),
            "primary_name": diagnosis.get("primary_diagnosis", "Unknown"),
            "confidence": diagnosis.get("confidence", 0.0)
        },
        "stage_evaluation": {
            "stage_name": growth_stage.get("stage_name"),
            "source": growth_stage.get("source"),
            "is_confirmed": growth_stage.get("is_confirmed")
        },
        "treatment_candidates": [],
        "excluded_treatments": [],
        "safety_warnings": [],
        "dose_information": [],
        "management_practices": practices,
        "provenance": {
            "source": "FarmAssist Knowledge Base",
            "timestamp": "now"
        }
    }

    # Split treatments based on eligibility and dose safety
    for t in treatments:
        treatment_info = {
            "treatment": t["active_ingredient"],
            "formulation": t["formulation_type"],
            "trade_names": t["trade_names"],
            "method": t["application_method"],
            "stage_status": t["stage_status"], # ELIGIBLE, STAGE_UNSPECIFIED, PROHIBITED
            "dose_status": t["dose_status"],   # AVAILABLE, UNAVAILABLE
            "dose": t["dose"],
            "phi_days": t["phi_days"],
            "provenance": t["source_authority"]
        }
        
        if t["stage_status"] == "PROHIBITED":
            structured["excluded_treatments"].append(treatment_info)
            structured["safety_warnings"].append(
                f"{t['active_ingredient']} is PROHIBITED during {growth_stage.get('stage_name')} stage."
            )
        elif t["dose_status"] == "UNAVAILABLE":
            structured["excluded_treatments"].append(treatment_info)
            structured["safety_warnings"].append(
                f"{t['active_ingredient']} dose is UNAVAILABLE. Consult local agronomist."
            )
        else:
            structured["treatment_candidates"].append(treatment_info)
            structured["dose_information"].append({
                "treatment": t["active_ingredient"],
                "dose": t["dose"]
            })

    return structured
