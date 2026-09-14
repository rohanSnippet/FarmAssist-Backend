import logging
from typing import List, Dict, Any
from .models import (
    ChemicalTreatment, ManagementPractice, KnowledgeStatus, 
    KnowledgeChunk, CropDiagnosis
)

logger = logging.getLogger(__name__)

def get_deterministic_treatments(diagnosis: CropDiagnosis) -> List[Dict[str, Any]]:
    """
    Retrieves approved chemical treatments for a specific diagnosis directly from the SQL database.
    This guarantees 100% adherence to CIB&RC or ICAR recommendations and prevents hallucination.
    """
    logger.info(f"[Retrieval] Fetching deterministic treatments for {diagnosis}")
    
    treatments = ChemicalTreatment.objects.filter(
        diagnosis=diagnosis,
        status=KnowledgeStatus.APPROVED
    ).select_related('source')
    
    results = []
    for t in treatments:
        results.append({
            "active_ingredient": t.active_ingredient,
            "formulation_type": t.formulation_type,
            "trade_names": t.trade_name_examples,
            "dose": f"{t.dose_per_hectare_min} to {t.dose_per_hectare_max} {t.dose_unit} per hectare",
            "water_volume": t.water_volume_per_hectare,
            "application_method": t.application_method,
            "phi_days": t.pre_harvest_interval_days,
            "source_authority": t.source.source.organization,
            "source_tier": t.source.source.get_authority_tier_display(),
            "source_document": t.source.title
        })
        
    return results

def get_management_practices(diagnosis: CropDiagnosis, region: str = None) -> Dict[str, List[str]]:
    """
    Retrieves cultural, mechanical, and biological practices.
    Optionally filters by region for State-specific practices.
    """
    practices = ManagementPractice.objects.filter(diagnosis=diagnosis)
    
    # If a region is provided (e.g. Maharashtra), we prefer region-specific + All India
    if region:
        practices = practices.filter(
            region_applicability__icontains=region
        ) | practices.filter(region_applicability__isnull=True)
        
    results = {
        "CULTURAL": [],
        "MECHANICAL": [],
        "BIOLOGICAL": [],
        "BOTANICAL": []
    }
    
    for p in practices:
        results[p.practice_type].append(p.description)
        
    return results

def get_rag_context(diagnosis: CropDiagnosis, query: str = None) -> str:
    """
    Retrieves contextual information (symptoms, lifecycle) using Metadata-Filtered RAG.
    We NEVER use this for chemical dosing.
    """
    # In a full implementation, we would embed the `query` here 
    # and use pgvector's `cosine_distance` to find the most relevant chunks.
    # For now, we perform a metadata-filtered keyword lookup or return the primary symptoms.
    
    context = f"Pathogen: {diagnosis.pathogen.scientific_name}\n"
    if diagnosis.symptoms_description:
        context += f"Symptoms: {diagnosis.symptoms_description}\n"
        
    chunks = KnowledgeChunk.objects.filter(diagnosis=diagnosis)[:3]
    if chunks.exists():
        context += "Additional Authoritative Context:\n"
        for chunk in chunks:
            context += f"- {chunk.chunk_text}\n"
            
    return context
