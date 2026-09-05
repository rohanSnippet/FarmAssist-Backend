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

# --- Model Registries ---
# Crop-specific disease models
DISEASE_MODELS = {
    "tomato":     "plantdoc-s3o47/1",
    "grape":      "plantdoc-s3o47/1",
    "strawberry": "plantdoc-s3o47/1",
    "corn":       "plantdoc-s3o47/1",
    "apple":      "plantdoc-s3o47/1",
    "cotton":     "cotton-disease-detection-xevxs/1",
    "rice":       "rice-disease-detection-l6xxa/3",
    "wheat":      "wheat-disease-detection-zsn0p/1",
    "mango":      "mango-disease-8tddh/4",
    "coconut":    "coconut-tree-disease-detection-uiugr-pywob/1",
    "chilli":     "rafsan-hasan-pronoy-4yskb/chilli-disease-detection-iqlef-instant-1",
}

# Crop-specific pest models
PEST_MODELS = {
    "cotton": "cotton-pest-detection/1",
    "corn":   "fall-armyworm-detection/2",
    "maize":  "fall-armyworm-detection/2",
}

# Generic fallback models — always fires for unknown crops (fixes silent skip bug)
GENERIC_PEST_MODEL    = "crop-pest-detection-ip102/1"   # Best generic pest model on Roboflow
GENERIC_DISEASE_MODEL = "plantdoc-s3o47/1"              # Generic plant disease model

# Confidence threshold for all specialist engines
CONFIDENCE_THRESHOLD = 0.40

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
    "as": "Assamese (অসমীয়া)",
}


# =====================================================================
# STAGE 1 — CROP ROUTER  (Pl@ntNet / hint)
# =====================================================================
def identify_crop(image_bytes: bytes, fallback_crop: str = None) -> str:
    """
    Resolves the crop species from the image using Pl@ntNet API.
    Falls back to the user-provided hint, or 'general' if both fail.
    """
    if not PLANTNET_API_KEY:
        logger.warning("[Stage 1] PLANTNET_API_KEY not set — using hint fallback.")
        return (fallback_crop or "general").lower()

    url = f"https://my-api.plantnet.org/v2/identify/all?api-key={PLANTNET_API_KEY}"
    try:
        files = [("images", ("image.jpg", image_bytes, "image/jpeg"))]
        response = requests.post(url, files=files, timeout=6.0)

        if response.status_code == 200:
            results = response.json().get("results", [])
            if results:
                best_match   = results[0]
                species_name = best_match.get("species", {}).get("scientificNameWithoutAuthor", "").lower()
                common_names = best_match.get("species", {}).get("commonNames", [])

                combined = f"{species_name} {' '.join(common_names).lower()}"
                # Prefer an exact match to a known model-supported crop
                for target_crop in DISEASE_MODELS.keys():
                    if target_crop in combined:
                        return target_crop
                if common_names:
                    return common_names[0].lower()
    except Exception as e:
        logger.warning(f"[Stage 1] Pl@ntNet call failed: {e}")

    return (fallback_crop or "general").lower()


# =====================================================================
# STAGE 2 — MODEL ROUTER
# =====================================================================
def route_models(crop: str) -> tuple:
    """
    Selects the best pest and disease model IDs for the resolved crop.
    Always returns a valid model for BOTH engines — uses generic models
    as fallback so neither engine is ever silently skipped.
    """
    pest_model_id    = PEST_MODELS.get(crop, GENERIC_PEST_MODEL)
    disease_model_id = DISEASE_MODELS.get(crop, GENERIC_DISEASE_MODEL)

    logger.info(
        f"[Stage 2] MODEL ROUTER | crop='{crop}' | "
        f"pest_model='{pest_model_id}' | disease_model='{disease_model_id}'"
    )
    return pest_model_id, disease_model_id


# =====================================================================
# STAGE 3 — PEST ENGINE + DISEASE ENGINE  (Simultaneous)
# =====================================================================
def _query_roboflow(model_id: str, image_bytes: bytes) -> list:
    """Low-level Roboflow REST call. Returns the raw predictions list."""
    if not ROBOFLOW_API_KEY or not model_id:
        return []
    url = f"https://detect.roboflow.com/{model_id}"
    try:
        response = requests.post(
            url,
            params={"api_key": ROBOFLOW_API_KEY, "confidence": 35},
            files={"file": ("image.jpg", image_bytes, "image/jpeg")},
            timeout=8.0,
        )
        if response.status_code == 200:
            return response.json().get("predictions", [])
    except Exception as e:
        logger.error(f"[Stage 3] Roboflow query failed for model '{model_id}': {e}")
    return []


def run_pest_disease_engines(pest_model_id: str, disease_model_id: str, image_bytes: bytes) -> tuple:
    """
    Fires the Pest Engine and Disease Engine simultaneously using a thread pool.
    Returns (pest_predictions, disease_predictions) as raw Roboflow output lists.
    """
    pest_preds    = []
    disease_preds = []

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            executor.submit(_query_roboflow, pest_model_id,    image_bytes): "pest",
            executor.submit(_query_roboflow, disease_model_id, image_bytes): "disease",
        }
        for future in as_completed(futures):
            engine = futures[future]
            try:
                if engine == "pest":
                    pest_preds = future.result()
                else:
                    disease_preds = future.result()
            except Exception as e:
                logger.error(f"[Stage 3] {engine.upper()} ENGINE thread failed: {e}")

    logger.info(
        f"[Stage 3] PEST ENGINE: {len(pest_preds)} raw predictions | "
        f"DISEASE ENGINE: {len(disease_preds)} raw predictions"
    )
    return pest_preds, disease_preds


# =====================================================================
# STAGE 4 — RESULT NORMALIZER
# =====================================================================
def normalize_results(pest_preds: list, disease_preds: list) -> dict:
    """
    Merges raw outputs from both engines into a single unified schema.
    Picks the highest-confidence prediction from each engine and builds
    the structured detections list. Makes NO verdict — that is Stage 5.
    """
    best_pest    = max(pest_preds,    key=lambda x: x.get("confidence", 0), default=None)
    best_disease = max(disease_preds, key=lambda x: x.get("confidence", 0), default=None)

    pest_conf    = best_pest.get("confidence",    0.0) if best_pest    else 0.0
    disease_conf = best_disease.get("confidence", 0.0) if best_disease else 0.0

    detections = []

    if (
        best_pest
        and pest_conf >= CONFIDENCE_THRESHOLD
        and "healthy" not in best_pest.get("class", "").lower()
    ):
        detections.append({
            "type":       "pest",
            "name":       best_pest["class"],
            "confidence": round(pest_conf, 2),
            "box":        {k: best_pest[k] for k in ("x", "y", "width", "height") if k in best_pest},
        })

    if (
        best_disease
        and disease_conf >= CONFIDENCE_THRESHOLD
        and "healthy" not in best_disease.get("class", "").lower()
    ):
        detections.append({
            "type":       "disease",
            "name":       best_disease["class"],
            "confidence": round(disease_conf, 2),
            "box":        {k: best_disease[k] for k in ("x", "y", "width", "height") if k in best_disease},
        })

    logger.info(
        f"[Stage 4] RESULT NORMALIZER | "
        f"pest_conf={round(pest_conf, 2)}, disease_conf={round(disease_conf, 2)}, "
        f"valid_detections={len(detections)}"
    )
    return {
        "pest_conf":    pest_conf,
        "disease_conf": disease_conf,
        "best_pest":    best_pest,
        "best_disease": best_disease,
        "detections":   detections,
    }


# =====================================================================
# STAGE 5 — DECISION ENGINE
# =====================================================================
def run_decision_engine(normalized: dict, crop: str) -> dict:
    """
    Evaluates the normalized result and emits exactly one of these named states:
      - 'healthy'   : a healthy class was detected above threshold
      - 'pest'      : pest confirmed above threshold
      - 'disease'   : disease confirmed above threshold
      - 'mix_both'  : both pest AND disease confirmed above threshold
      - 'uncertain' : neither engine reached threshold — triggers Controlled Fallback

    'uncertain' is a first-class state — it is the ONLY path to Stage 6.
    """
    pest_conf    = normalized["pest_conf"]
    disease_conf = normalized["disease_conf"]
    best_pest    = normalized["best_pest"]
    best_disease = normalized["best_disease"]
    detections   = normalized["detections"]

    has_pest = (
        pest_conf >= CONFIDENCE_THRESHOLD
        and best_pest is not None
        and "healthy" not in best_pest.get("class", "").lower()
    )
    has_disease = (
        disease_conf >= CONFIDENCE_THRESHOLD
        and best_disease is not None
        and "healthy" not in best_disease.get("class", "").lower()
    )

    # Neither engine is confident enough about anything
    if not has_pest and not has_disease:
        # Check if a model explicitly predicted a "healthy" class above threshold
        pest_says_healthy = (
            best_pest is not None
            and "healthy" in best_pest.get("class", "").lower()
            and pest_conf >= CONFIDENCE_THRESHOLD
        )
        disease_says_healthy = (
            best_disease is not None
            and "healthy" in best_disease.get("class", "").lower()
            and disease_conf >= CONFIDENCE_THRESHOLD
        )

        if pest_says_healthy or disease_says_healthy:
            condition_type = "healthy"
            primary_diag   = "Healthy Crop"
            conf           = max(pest_conf, disease_conf)
            logger.info(f"[Stage 5] DECISION ENGINE → 'healthy' (conf={round(conf, 2)})")
        else:
            # True uncertain — no model is confident about anything
            logger.info(
                "[Stage 5] DECISION ENGINE → 'uncertain' "
                f"(pest_conf={round(pest_conf, 2)}, disease_conf={round(disease_conf, 2)}) "
                "— routing to Controlled Fallback."
            )
            return {
                "crop":              crop,
                "condition_type":    "uncertain",
                "primary_diagnosis": "Uncertain",
                "confidence":        round(max(pest_conf, disease_conf), 2),
                "detections":        detections,
                "source":            "specialist_ensemble_uncertain",
            }

    elif has_pest and has_disease:
        condition_type = "mix_both"
        primary_diag   = f"{best_disease['class']} & {best_pest['class']}"
        conf           = (pest_conf + disease_conf) / 2
        logger.info(f"[Stage 5] DECISION ENGINE → 'mix_both' (conf={round(conf, 2)})")

    elif has_pest:
        condition_type = "pest"
        primary_diag   = best_pest["class"]
        conf           = pest_conf
        logger.info(f"[Stage 5] DECISION ENGINE → 'pest' | '{primary_diag}' (conf={round(conf, 2)})")

    else:  # has_disease only
        condition_type = "disease"
        primary_diag   = best_disease["class"]
        conf           = disease_conf
        logger.info(f"[Stage 5] DECISION ENGINE → 'disease' | '{primary_diag}' (conf={round(conf, 2)})")

    return {
        "crop":              crop,
        "condition_type":    condition_type,
        "primary_diagnosis": primary_diag,
        "confidence":        round(conf, 2),
        "detections":        detections,
        "source":            "specialist_ensemble",
    }


# =====================================================================
# STAGE 6 — CONTROLLED FALLBACK  (Gemini Zero-Shot)
# =====================================================================
def run_gemini_fallback(image_bytes: bytes, crop: str) -> dict:
    """
    Gemini 2.5 Flash zero-shot vision classifier.
    ONLY called when the Decision Engine returns 'uncertain'.
    Returns a dict compatible with the main result schema.
    """
    if not gemini_client:
        logger.warning("[Stage 6] Gemini client unavailable — returning unknown.")
        return {
            "crop":          crop,
            "category":      "unknown",
            "name":          "Unidentified Condition",
            "confidence":    0.3,
            "affected_area": 0,
        }

    prompt = f"""
    Analyze this crop image ({crop}). Determine whether it exhibits insect pest damage,
    disease symptoms, or is healthy. Also identify the crop if it is unknown or general.
    Return strictly JSON with keys:
    {{
      "crop": "<specific crop name>",
      "category": "pest" | "disease" | "healthy" | "mix_both",
      "diagnosis_name": "<specific name of pest or disease, or 'Healthy Crop'>",
      "confidence": <float 0.0 to 1.0>,
      "affected_area_percentage": <int>
    }}
    """
    try:
        response = gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                prompt,
            ],
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
        data = json.loads(response.text)
        logger.info(
            f"[Stage 6] CONTROLLED FALLBACK | "
            f"category='{data.get('category')}', confidence={data.get('confidence')}"
        )
        return {
            "crop":          data.get("crop", crop),
            "category":      data.get("category", "unknown"),
            "name":          data.get("diagnosis_name", "Unknown Issue"),
            "confidence":    float(data.get("confidence", 0.5)),
            "affected_area": data.get("affected_area_percentage", 10),
        }
    except Exception as e:
        logger.error(f"[Stage 6] Gemini fallback failed: {e}")
        return {
            "crop":          crop,
            "category":      "unknown",
            "name":          "Unidentified Issue",
            "confidence":    0.3,
            "affected_area": 0,
        }


# =====================================================================
# STAGE 7 & 8 — KNOWLEDGE BASE + ADVISORY ENGINE + LOCALIZATION
# =====================================================================
def generate_treatment_advisory(diagnosis_data: dict, lang_code: str = "en") -> str:
    """
    Uses Gemini 2.5 Flash as the agronomic Knowledge Base to generate
    an IPM treatment plan. Output is localized to the user's language (Stage 8).
    """
    if not gemini_client:
        return "1. Service unavailable.\n2. Please try again later.\n3. Contact local KVK."

    target_lang = LANGUAGE_MAPPING.get(lang_code, "English")
    condition   = diagnosis_data["condition_type"]
    diagnosis   = diagnosis_data["primary_diagnosis"]
    crop        = diagnosis_data["crop"]

    logger.info(
        f"[Stage 7] ADVISORY ENGINE | crop='{crop}', "
        f"diagnosis='{diagnosis}', lang='{target_lang}'"
    )

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
            contents=grounded_prompt,
        )
        logger.info("[Stage 8] LOCALIZATION complete. Advisory ready.")
        return response.text.strip()
    except Exception as e:
        logger.error(f"[Stage 7] Advisory generation failed: {e}")
        return "1. Error fetching advice.\n2. Apply general organic fungicide.\n3. Monitor closely."


# =====================================================================
# MAIN CONTROLLER — Exact Workflow Orchestration
# =====================================================================
def process_crop_diagnostic_pipeline(
    image_bytes: bytes,
    crop_hint: str = None,
    lang_code: str = "en",
) -> dict:
    """
    Orchestrates the full FarmAssist diagnostic pipeline in exact workflow order:

    IMAGE
      -> [Stage 1]  CROP ROUTER         (Pl@ntNet / hint -> resolved crop)
      -> [Stage 2]  MODEL ROUTER        (select pest + disease model IDs)
      -> [Stage 3]  PEST ENGINE         (concurrent Roboflow)
                    DISEASE ENGINE      (concurrent Roboflow)
      -> [Stage 4]  RESULT NORMALIZER
      -> [Stage 5]  DECISION ENGINE     -> healthy | pest | disease | mix_both | uncertain
                                               | only when condition == 'uncertain'
      -> [Stage 6]  CONTROLLED FALLBACK (Gemini zero-shot)
      -> [Stage 7]  KNOWLEDGE BASE + ADVISORY ENGINE
      -> [Stage 8]  LOCALIZATION
      -> API RESPONSE
    """
    logger.info("=" * 60)
    logger.info("STARTING CROP DIAGNOSTIC PIPELINE")
    logger.info("=" * 60)

    # -- Stage 1: Crop Router ------------------------------------------
    logger.info(f"[Stage 1] CROP ROUTER | hint='{crop_hint}'")
    detected_crop = identify_crop(image_bytes, fallback_crop=crop_hint)
    logger.info(f"[Stage 1] Resolved crop -> '{detected_crop}'")

    # -- Stage 2: Model Router -----------------------------------------
    pest_model_id, disease_model_id = route_models(detected_crop)

    # -- Stage 3: Pest + Disease Engines (Simultaneous) ----------------
    pest_preds, disease_preds = run_pest_disease_engines(
        pest_model_id, disease_model_id, image_bytes
    )

    # -- Stage 4: Result Normalizer ------------------------------------
    normalized = normalize_results(pest_preds, disease_preds)

    # -- Stage 5: Decision Engine --------------------------------------
    result = run_decision_engine(normalized, detected_crop)

    # -- Stage 6: Controlled Fallback — ONLY fires for 'uncertain' -----
    if result["condition_type"] == "uncertain":
        fallback = run_gemini_fallback(image_bytes, detected_crop)
        detected_crop = fallback.get("crop", detected_crop)
        result.update({
            "crop":              detected_crop,
            "condition_type":    fallback["category"],
            "primary_diagnosis": fallback["name"],
            "confidence":        fallback["confidence"],
            "source":            "gemini_zero_shot_fallback",
        })
    else:
        logger.info(
            f"[Stage 6] CONTROLLED FALLBACK skipped "
            f"(condition='{result['condition_type']}')"
        )

    # -- Stage 7 & 8: Advisory Engine + Localization -------------------
    result["advisory"] = generate_treatment_advisory(result, lang_code=lang_code)
    result["language"] = lang_code

    logger.info("=" * 60)
    logger.info(
        f"PIPELINE COMPLETE | crop='{detected_crop}' | "
        f"condition='{result['condition_type']}' | "
        f"confidence={result['confidence']} | source='{result['source']}'"
    )
    logger.info("=" * 60)
    return result
