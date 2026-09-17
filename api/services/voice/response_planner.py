import json
import logging
from api.ai_engine import gemini_client
from google.genai import types
from .schemas import ResponsePlan, UIAction

logger = logging.getLogger(__name__)

def generate_clarification_response(language_code: str, session_id: str, options: list) -> ResponsePlan:
    """Generates a response asking the user to clarify which farm they meant."""
    names = [opt['name'] for opt in options]
    names_str = ", ".join(names)
    
    prompt = f"""
    The user asked a question about a farm, but they have multiple farms matching their description: {names_str}.
    Please write a short, polite sentence asking them which farm they meant.
    Respond in the language: {language_code}.
    Return ONLY a JSON object:
    {{
      "speech": "the translated clarification question"
    }}
    """
    
    speech = "Could you clarify which farm you mean?"
    if gemini_client:
        try:
            response = gemini_client.models.generate_content(
                model="gemini-3.6-flash",
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json")
            )
            data = json.loads(response.text)
            speech = data.get("speech", speech)
        except Exception as e:
            logger.error(f"Failed to generate clarification: {e}")
            
    return ResponsePlan(
        speech=speech,
        ui_action=UIAction(type="AWAIT_CLARIFICATION", params={}),
        next_state="WAITING_FOR_USER_ACTION",
        session_id=session_id,
        language_code=language_code
    )

def generate_advisory_response(advisory_dict: dict, language_code: str, session_id: str, ui_context: dict) -> ResponsePlan:
    """Explains a StructuredAdvisory and guides the user."""
    
    prompt = f"""
    You are a helpful agricultural assistant for FarmAssist. 
    Explain this crop diagnosis and treatment advisory to a farmer.
    Keep it simple, avoid technical UI jargon. Do NOT invent doses if 'dose_status' is UNAVAILABLE.
    Translate your explanation to: {language_code}.
    
    Advisory Data:
    {json.dumps(advisory_dict, indent=2)}
    
    Return ONLY a JSON object:
    {{
      "speech": "your simple explanation in the target language"
    }}
    """
    
    speech = "I have the results of the scan."
    if gemini_client:
        try:
            response = gemini_client.models.generate_content(
                model="gemini-3.6-flash",
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json")
            )
            data = json.loads(response.text)
            speech = data.get("speech", speech)
        except Exception as e:
            logger.error(f"Failed to generate advisory speech: {e}")
            
    return ResponsePlan(
        speech=speech,
        ui_action=UIAction(type="OPEN_SCAN_RESULT", params={"scan_job_id": ui_context.get("scan_job_id")}),
        next_state="PRESENTING_ADVISORY",
        session_id=session_id,
        language_code=language_code
    )

def generate_standard_response(intent: str, domain_data: dict, language_code: str, session_id: str) -> ResponsePlan:
    """Generates standard conversational responses."""
    
    prompt = f"""
    You are FarmAssist, a helpful agricultural assistant.
    The user's intent was: {intent}
    The backend returned this data: {json.dumps(domain_data)}
    
    Provide a simple, helpful response in: {language_code}.
    Do not mention 'the database' or 'API'. Act like a human assistant.
    
    CRITICAL: If the user's intent involves an action they must take (like START_CROP_DIAGNOSTIC_SCAN), you MUST explicitly tell them what to do next on the screen (e.g., "Please click the camera button to take a photo of the affected crop leaf so I can analyze the disease."). Give clear, step-by-step guidance on why they are doing this and how to do it.
    
    Return ONLY a JSON object:
    {{
      "speech": "the translated explanation"
    }}
    """
    
    speech = "Okay."
    if gemini_client:
        try:
            response = gemini_client.models.generate_content(
                model="gemini-3.6-flash",
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json")
            )
            data = json.loads(response.text)
            speech = data.get("speech", speech)
        except Exception as e:
            logger.error(f"Failed to generate standard speech: {e}")
            
    # Determine UI Action based on intent
    ui_type = "NONE"
    next_state = "IDLE"
    
    if intent == "START_CROP_DIAGNOSTIC_SCAN":
        ui_type = "OPEN_SCANNER"
        next_state = "WAITING_FOR_SCAN_IMAGE"
    elif intent == "GET_FARM_OVERVIEW":
        ui_type = "OPEN_FARMS"
    elif intent == "GET_CROP_STATUS":
        ui_type = "OPEN_FARM"
        
    return ResponsePlan(
        speech=speech,
        ui_action=UIAction(type=ui_type, params={"farm_id": domain_data.get("farm_id")}),
        next_state=next_state,
        session_id=session_id,
        language_code=language_code
    )
