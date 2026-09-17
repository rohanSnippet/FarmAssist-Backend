import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

ALLOWED_ACTIONS = {
    "OPEN_DASHBOARD",
    "OPEN_FARMS",
    "OPEN_FARM",
    "OPEN_SCANNER",
    "OPEN_SCAN_RESULT",
    "OPEN_NOTIFICATIONS",
    "OPEN_PROFILE",
    "GET_WEATHER",
    "VIEW_ADVISORY",
    "OPEN_CROP_RECOMMENDATIONS",
    "OPEN_RECOMMENDATION_HISTORY",
    "OPEN_PEST_HISTORY"
}

def execute_voice_action(audio_b64: str, mime_type: str, user, default_language: str = "en-IN") -> Dict[str, Any]:
    """
    Validates a Gemini-extracted intent against an allowlist and executes it securely.
    Provides localized conversational responses by auto-detecting the spoken language directly from audio.
    """
    import json
    import base64
    from api.ai_engine import gemini_client
    from google.genai import types

    intent = {"action": "UNKNOWN", "params": {}, "message": "I could not process that.", "language_code": default_language}
    if gemini_client:
        audio_bytes = base64.b64decode(audio_b64)
        audio_part = types.Part.from_bytes(data=audio_bytes, mime_type=mime_type)
        
        prompt = f"""
        1. Listen to the attached audio.
        2. Auto-detect the language spoken (primarily expecting Marathi, Hindi, or English).
        3. Extract the user intent.
        4. Formulate a short, conversational response message translated strictly into their natively detected language.
        
        Return JSON exactly matching this structure:
        {{
            "action": "one of {ALLOWED_ACTIONS} or UNKNOWN",
            "params": {{ "farm_id": 123 }}, // Only if specified and applicable.
            "message": "A short acknowledgment translated into the detected language.",
            "language_code": "The BCP-47 code of the detected language (e.g. 'hi-IN', 'mr-IN', 'en-IN')"
        }}
        """
        try:
            response = gemini_client.models.generate_content(
                model="gemini-3.6-flash",
                contents=[audio_part, prompt],
                config=types.GenerateContentConfig(response_mime_type="application/json")
            )
            intent = json.loads(response.text)
        except Exception as e:
            logger.error(f"Failed to parse intent: {e}")
            
    action = intent.get("action")
    params = intent.get("params", {})
    message = intent.get("message", "Action processed.")
    language_code = intent.get("language_code", default_language)
    
    if not action or action not in ALLOWED_ACTIONS:
        return {
            "status": "error",
            "message": message,
            "language_code": language_code,
            "executed": False
        }
        
    # Implement strict backend authorization for contextual actions
    if action == "OPEN_FARM":
        farm_id = params.get("farm_id")
        if not farm_id:
            return {"status": "error", "message": message, "language_code": language_code, "executed": False}
        
        from api.models import Farm
        # Authorization depends explicitly on the authenticated user
        if not Farm.objects.filter(id=farm_id, user=user).exists():
            return {"status": "error", "message": "Farm not found.", "language_code": "en-IN", "executed": False}
        
        return {
            "status": "success",
            "action": action,
            "params": {"farm_id": farm_id},
            "message": message,
            "language_code": language_code,
            "executed": True
        }
        
    # General navigation
    return {
        "status": "success",
        "action": action,
        "params": params,
        "message": message,
        "language_code": language_code,
        "executed": True
    }
