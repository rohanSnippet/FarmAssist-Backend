import os
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# --- API Keys & Clients ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ROBOFLOW_API_KEY = os.getenv("ROBOFLOW_API_KEY")
PLANTNET_API_KEY = os.getenv("PLANTNET_API_KEY")

gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# --- Verified Model Registry ---
# Mapping verified disease models and specialized/generic pest models
DISEASE_MODELS = {
    "tomato": "plantdoc-s3o47/1",
    "grape": "plantdoc-s3o47/1",
    "strawberry": "plantdoc-s3o47/1",
    "corn": "plantdoc-s3o47/1",
    "apple": "plantdoc-s3o47/1",
    "cotton": "cotton-disease-detection-xevxs/1",
    "rice": "rice-disease-detection-l6xxa/3",
    "wheat": "wheat-disease-detection-zsn0p/1",
    "mango": "mango-disease-8tddh/4",
    "coconut": "coconut-tree-disease-detection-uiugr-pywob/1",
    "chilli": "rafsan-hasan-pronoy-4yskb/chilli-disease-detection-iqlef-instant-1",
}

# Crop-specific pest models or fallback to generic pest detector
GENERIC_PEST_MODEL = "crop-pest-detection-ip102/1"  # Best generic pre-trained pest model on Roboflow
PEST_MODELS = {
    "cotton": "cotton-pest-detection/1",
    "corn": "fall-armyworm-detection/2",
    "maize": "fall-armyworm-detection/2",
}

# Supported languages in FarmAssist i18n
LANGUAGE_MAPPING = {
    "en": "English",
    "hi": "Hindi (हिंदी)",
    "mr": "Marathi (मराठी)",
    "bn": "Bengali (বাংলা)",
    "ta": "Tamil (தமிழ்)",
    "te": "Telugu (తెలుగు)",
    "kn": "Kannada (ಕನ್ನಡ)",
    "gu": "Gujarati (ગુજરાતી)",
    "pa": "Punjabi (ਪੰਜਾਬੀ)",
    "ur": "Urdu (اردو)",
    "or": "Odia (ଓଡ଼ିଆ)",
    "as": "Assamese (অসমীয়া)"
}


# =====================================================================
# 1. CROP IDENTIFIER (Pl@ntNet API)
# =====================================================================
def identify_crop(image_bytes: bytes, fallback_crop: str = None) -> str:
    """
    Identifies crop species using Pl@ntNet API.
    Falls back to user-provided hint or general inspection if identification fails.
    """
    if not PLANTNET_API_KEY:
        return (fallback_crop or "general").lower()

    url = f"https://my-api.plantnet.org/v2/identify/all?api-key={PLANTNET_API_KEY}"
    try:
        files = [('images', ('image.jpg', image_bytes, 'image/jpeg'))]
        response = requests.post(url, files=files, timeout=6.0)
        
        if response.status_code == 200:
            results = response.json().get("results", [])
            if results:
                best_match = results[0]
                species_name = best_match.get("species", {}).get("scientificNameWithoutAuthor", "").lower()
                common_names = best_match.get("species", {}).get("commonNames", [])
                
                # Check for known agricultural matches
                combined = f"{species_name} {' '.join(common_names).lower()}"
                for target_crop in DISEASE_MODELS.keys():
                    if target_crop in combined:
                        return target_crop
                if common_names:
                    return common_names[0].lower()
    except Exception as e:
        logger.warning(f"Pl@ntNet identification failed: {e}")

    return (fallback_crop or "general").lower()


# =====================================================================
# 2. ROBOFLOW INFERENCE ENGINE
# =====================================================================
def query_roboflow_model(model_id: str, image_bytes: bytes) -> list:
    """Queries Roboflow Serverless REST endpoint for a specified model ID."""
    if not ROBOFLOW_API_KEY or not model_id:
        return []

    url = f"https://detect.roboflow.com/{model_id}"
    try:
        response = requests.post(
            url,
            params={"api_key": ROBOFLOW_API_KEY, "confidence": 35},
            files={"file": image_bytes},
            timeout=8.0
        )
        if response.status_code == 200:
            return response.json().get("predictions", [])
    except Exception as e:
        logger.error(f"Error querying Roboflow model {model_id}: {e}")
    return []


# =====================================================================
# 3. FALLBACK TO GEMINI ZERO-SHOT
# =====================================================================
def run_gemini_fallback(image_bytes: bytes, crop: str) -> dict:
    """Zero-shot vision classifier when specialized models are unavailable or unconfident."""
    if not gemini_client:
        return {"category": "unknown", "name": "Unidentified Condition", "confidence": 0.3}

    prompt = f"""
    Analyze this crop image ({crop}). Determine whether it exhibits insect pest damage, disease symptoms, or is healthy.
    Return strictly JSON with keys:
    {{
      "category": "pest" | "disease" | "healthy" | "both",
      "diagnosis_name": "<specific name of pest or disease>",
      "confidence": <float 0.0 to 1.0>,
      "affected_area_percentage": <int>
    }}
    """
    try:
        response = gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                prompt
            ],
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        data = json.loads(response.text)
        return {
            "category": data.get("category", "unknown"),
            "name": data.get("diagnosis_name", "Unknown Issue"),
            "confidence": float(data.get("confidence", 0.5)),
            "affected_area": data.get("affected_area_percentage", 10)
        }
    except Exception as e:
        logger.error(f"Gemini fallback failed: {e}")
        return {"category": "unknown", "name": "Unidentified Issue", "confidence": 0.3}


# =====================================================================
# 4. SIMULTANEOUS ROUTER & RESPONSE NORMALIZER
# =====================================================================
def simultaneous_pest_disease_scan(image_bytes: bytes, crop: str) -> dict:
    """
    Concurrently triggers pest and disease models.
    Normalizes outputs and determines if the leaf has pest damage, disease, or both.
    """
    disease_model_id = DISEASE_MODELS.get(crop)
    pest_model_id = PEST_MODELS.get(crop, GENERIC_PEST_MODEL)

    pest_preds = []
    disease_preds = []

    # Run models concurrently
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {}
        if pest_model_id:
            futures[executor.submit(query_roboflow_model, pest_model_id, image_bytes)] = "pest"
        if disease_model_id:
            futures[executor.submit(query_roboflow_model, disease_model_id, image_bytes)] = "disease"

        for future in as_completed(futures):
            m_type = futures[future]
            try:
                if m_type == "pest":
                    pest_preds = future.result()
                else:
                    disease_preds = future.result()
            except Exception as e:
                logger.error(f"Model task failed for {m_type}: {e}")

    # Fallback to Gemini if no specialist models responded with confidence >= 0.40
    best_pest = max(pest_preds, key=lambda x: x.get("confidence", 0), default=None)
    best_disease = max(disease_preds, key=lambda x: x.get("confidence", 0), default=None)

    pest_conf = best_pest.get("confidence", 0.0) if best_pest else 0.0
    disease_conf = best_disease.get("confidence", 0.0) if best_disease else 0.0

    if pest_conf < 0.40 and disease_conf < 0.40:
        fallback = run_gemini_fallback(image_bytes, crop)
        return {
            "crop": crop,
            "condition_type": fallback["category"],
            "primary_diagnosis": fallback["name"],
            "confidence": fallback["confidence"],
            "detections": [],
            "source": "gemini_zero_shot_fallback"
        }

    # Normalize output format and decide issue type
    detections = []
    has_pest = pest_conf >= 0.40 and "healthy" not in best_pest.get("class", "").lower()
    has_disease = disease_conf >= 0.40 and "healthy" not in best_disease.get("class", "").lower()

    if has_pest:
        detections.append({
            "type": "pest",
            "name": best_pest["class"],
            "confidence": round(best_pest["confidence"], 2),
            "box": {k: best_pest[k] for k in ("x", "y", "width", "height") if k in best_pest}
        })

    if has_disease:
        detections.append({
            "type": "disease",
            "name": best_disease["class"],
            "confidence": round(best_disease["confidence"], 2),
            "box": {k: best_disease[k] for k in ("x", "y", "width", "height") if k in best_disease}
        })

    if has_pest and has_disease:
        condition_type = "mix_both"
        primary_diag = f"{best_disease['class']} & {best_pest['class']}"
        conf = (pest_conf + disease_conf) / 2
    elif has_pest:
        condition_type = "pest"
        primary_diag = best_pest["class"]
        conf = pest_conf
    elif has_disease:
        condition_type = "disease"
        primary_diag = best_disease["class"]
        conf = disease_conf
    else:
        condition_type = "healthy"
        primary_diag = "Healthy Crop"
        conf = max(pest_conf, disease_conf, 0.85)

    return {
        "crop": crop,
        "condition_type": condition_type,
        "primary_diagnosis": primary_diag,
        "confidence": round(conf, 2),
        "detections": detections,
        "source": "specialist_ensemble"
    }


# =====================================================================
# 5. LLM KNOWLEDGE BASE (Grounded Treatment & IPM in Target Language)
# =====================================================================
def generate_treatment_advisory(diagnosis_data: dict, lang_code: str = "en") -> str:
    """
    Generates strictly formatted IPM treatments. 
    """
    if not gemini_client:
        return "1. Service unavailable.\n2. Please try again later.\n3. Contact local KVK."

    target_lang = LANGUAGE_MAPPING.get(lang_code, "English")
    condition = diagnosis_data["condition_type"]
    diagnosis = diagnosis_data["primary_diagnosis"]
    crop = diagnosis_data["crop"]

    logger.info(f"PHASE 4: Generating LLM Advisory for {diagnosis} on {crop} in {target_lang}")

    grounded_prompt = f"""
    Crop: {crop}
    Condition: {condition}
    Diagnosis: {diagnosis}
    Language: {target_lang}

    You are an expert agronomist. Provide EXACTLY 3 short bullet points for treatment. 
    RULES:
    - Point 1: Immediate action (max 15 words).
    - Point 2: Chemical/Organic treatment with exact dosage (max 25 words).
    - Point 3: Prevention step (max 15 words).
    - NO introductory sentences. NO concluding sentences.
    - Output strictly in the requested Language script.
    - Use the exact format: 
    1. [Text]
    2. [Text]
    3. [Text]
    """

    try:
        response = gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=grounded_prompt
        )
        logger.info("PHASE 5: Advisory generated successfully.")
        return response.text.strip()
    except Exception as e:
        logger.error(f"Advisory generation failed: {e}")
        return "1. Error fetching advice.\n2. Apply general organic fungicide.\n3. Monitor closely."


# ==================================================
# 6. MAIN CONTROLLER
# ===================================================
def process_crop_diagnostic_pipeline(image_bytes: bytes, crop_hint: str = None, lang_code: str = "en") -> dict:
    """
    Complete workflow with phase logging.
    """
    logger.info("=== STARTING CROP DIAGNOSTIC PIPELINE ===")
    
    # Phase 1: Identify crop
    logger.info(f"PHASE 1: Identifying crop. Hint provided: {crop_hint}")
    detected_crop = identify_crop(image_bytes, fallback_crop=crop_hint)
    logger.info(f"PHASE 1 RESULT: Resolved crop to '{detected_crop}'")

    # Phase 2 & 3: Run concurrent router & normalize output
    logger.info("PHASE 2 & 3: Triggering simultaneous vision models and normalizing output...")
    normalized_results = simultaneous_pest_disease_scan(image_bytes, detected_crop)
    logger.info(f"PHASE 3 RESULT: Diagnosis={normalized_results['primary_diagnosis']}, Confidence={normalized_results['confidence']}")

    # Phase 4 & 5: Generate localized IPM advisory
    advisory = generate_treatment_advisory(normalized_results, lang_code=lang_code)

    normalized_results["advisory"] = advisory
    normalized_results["language"] = lang_code
    
    logger.info("=== PIPELINE COMPLETE ===")
    return normalized_results
    