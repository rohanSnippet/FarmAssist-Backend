import json
import base64
import logging
import uuid
from typing import Dict, Any

from api.ai_engine import gemini_client
from google.genai import types

from .models import WorkflowEvent
from .workflow_engine import WorkflowEngine
from api.services.farmer_context_service import get_farmer_context_summary
from api.models import VoiceTask

logger = logging.getLogger(__name__)

def handle_workflow_event(user, request_data: dict) -> Dict[str, Any]:
    """
    1. Rehydrates the event.
    2. If event is USER_SPOKE with audio, calls Gemini to extract semantic intent.
    3. Passes to WorkflowEngine.
    """
    event_id = request_data.get('event_id') or str(uuid.uuid4())
    task_id = request_data.get('task_id')
    event_type = request_data.get('event_type')
    payload = request_data.get('payload', {})
    ui_context = request_data.get('ui_context', {})
    
    if event_type == "USER_SPOKE" and 'audio_b64' in payload:
        farmer_context = get_farmer_context_summary(user)
        
        # Get active task state if any
        workflow_state = None
        if task_id:
            try:
                task = VoiceTask.objects.get(id=task_id, user=user)
                workflow_state = {
                    "workflow": task.workflow_id,
                    "step": task.current_step,
                    "collected_data": task.collected_data
                }
            except VoiceTask.DoesNotExist:
                pass

        # Call Gemini for extraction
        extracted = _extract_intent_from_audio(
            payload['audio_b64'], 
            payload.get('mime_type', 'audio/webm'), 
            farmer_context, 
            ui_context,
            workflow_state
        )
        payload['extracted_entities'] = extracted
        # If it's a new task, we determine workflow_id from the intent
        if not task_id:
            intent = extracted.get("intent", "UNKNOWN")
            workflow_id_map = {
                "ADD_FARM": "ADD_FARM",
                "START_CROP_DIAGNOSTIC_SCAN": "CROP_SCAN",
                "GET_FARM_OVERVIEW": "FARM_OVERVIEW",
                "GET_STAGE_ADVISORY": "STAGE_ADVISORY",
                "GET_WATER_REQUIREMENT": "CROP_QUESTION",
            }
            mapped_workflow = workflow_id_map.get(intent)
            if not mapped_workflow:
                return {"speech": "I didn't quite catch that. Could you repeat?", "task": None}
            payload["workflow_id"] = mapped_workflow

    event = WorkflowEvent(
        event_id=event_id,
        event_type=event_type,
        task_id=task_id,
        payload=payload,
        ui_context=ui_context
    )
    
    response = WorkflowEngine.process_event(user, event)
    return response.to_dict()

def _extract_intent_from_audio(audio_b64: str, mime_type: str, farmer_context: dict, ui_context: dict, workflow_state: dict = None) -> dict:
    if not gemini_client:
        return {}
        
    try:
        audio_bytes = base64.b64decode(audio_b64)
        audio_part = types.Part.from_bytes(data=audio_bytes, mime_type=mime_type)
        
        prompt = f"""
        Extract the user's intent and any entities from this audio.
        The user may be speaking in an Indian regional language (e.g. Marathi, Hindi) or English.
        
        Context: {json.dumps(farmer_context)}
        UI Context: {json.dumps(ui_context)}
        Workflow State (Active Task): {json.dumps(workflow_state) if workflow_state else 'None'}
        
        If a Workflow State is provided, focus on extracting the expected entity for that step (e.g. if WAITING_FOR_CITY, look for a location).
        
        Recognized Intents: ADD_FARM, START_CROP_DIAGNOSTIC_SCAN, GET_FARM_OVERVIEW, GET_STAGE_ADVISORY, GET_WATER_REQUIREMENT, UNKNOWN
        
        Return ONLY valid JSON like this (include only found fields):
        {{
            "intent": "ADD_FARM",
            "farm_name": "...",
            "location": "...",
            "crop": "...",
            "planting_date": "...",
            "confirmation": "yes",
            "language": "mr" // Detected language code (e.g. mr, hi, en)
        }}
        """
        
        response = gemini_client.models.generate_content(
            model="gemini-3.6-flash",
            contents=[audio_part, prompt],
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        return json.loads(response.text)
    except Exception as e:
        logger.error(f"Failed to extract intent: {e}")
        return {}
