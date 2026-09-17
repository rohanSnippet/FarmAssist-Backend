import logging
from django.db import transaction
from api.models import VoiceTask, VoiceEventLog
from .models import WorkflowEvent, WorkflowResponse
from .workflow_registry import get_workflow_class
from api.ai_engine import gemini_client
import json

logger = logging.getLogger(__name__)

class WorkflowEngine:
    """
    Orchestrates VoiceTasks, providing pessimistic locking for concurrency and
    idempotency checks against duplicate events (like Celery completing twice).
    """
    
    @classmethod
    def process_event(cls, user, event: WorkflowEvent) -> WorkflowResponse:
        """
        Process a WorkflowEvent and return a WorkflowResponse.
        """
        # Idempotency check before obtaining any task locks
        if VoiceEventLog.objects.filter(event_id=event.event_id).exists():
            logger.warning(f"Event {event.event_id} already processed. Ignoring.")
            return WorkflowResponse(speech="This request was already processed.")

        task_id = event.task_id
        
        with transaction.atomic():
            if task_id:
                # Use select_for_update for optimistic/pessimistic concurrency
                try:
                    task = VoiceTask.objects.select_for_update().get(id=task_id, user=user)
                except VoiceTask.DoesNotExist:
                    logger.error(f"Task {task_id} not found for user {user.id}")
                    # Could be an expired task or invalid
                    return WorkflowResponse(speech="I lost track of what we were doing. Let's start over.")
            else:
                # It's a new task, we don't have a workflow yet.
                # The VoiceIntentView/Service will need to classify the intent first!
                # For now, let's assume the event payload contains 'workflow_id' if starting a new one.
                workflow_id = event.payload.get('workflow_id')
                if not workflow_id:
                    # In a real scenario, we call intent_resolver here if it wasn't done before
                    # But the architecture suggests intent_resolver is called BEFORE workflow_engine
                    # If no workflow_id is available, we can't proceed
                    return WorkflowResponse(speech="I didn't understand that. Please try again.")
                
                task = VoiceTask(
                    user=user,
                    workflow_id=workflow_id,
                    status=VoiceTask.Status.ACTIVE,
                    current_step="START"
                )
                task.save()
            
            # Record the event for idempotency
            VoiceEventLog.objects.create(
                event_id=event.event_id,
                task=task,
                event_type=event.event_type,
                payload=event.payload
            )
            
            # Persist language if detected
            extracted_language = event.payload.get("extracted_entities", {}).get("language")
            if extracted_language:
                task.language = extracted_language

            # Handle global TASK_CANCEL
            if event.event_type == 'TASK_CANCEL':
                task.status = VoiceTask.Status.CANCELLED
                task.save()
                return WorkflowResponse(
                    speech="Conversation ended.",
                    task_info={
                        "id": str(task.id),
                        "status": task.status
                    }
                )

            # Get the workflow implementation
            try:
                workflow_cls = get_workflow_class(task.workflow_id)
                workflow = workflow_cls(task)
            except ValueError as e:
                logger.error(f"Error loading workflow: {e}")
                return WorkflowResponse(speech="I'm sorry, I don't know how to handle that workflow.")

            # Process the event
            response = workflow.process_event(event)

            # Save the mutated task
            task.save()
            
            # Translate speech if necessary
            if response.speech and task.language and not task.language.lower().startswith('en'):
                try:
                    prompt = f"Translate the following text to the language with code '{task.language}'. Return ONLY the translated text, nothing else. Text: {response.speech}"
                    translation_resp = gemini_client.models.generate_content(
                        model="gemini-3.6-flash",
                        contents=prompt
                    )
                    if translation_resp.text:
                        response.speech = translation_resp.text.strip()
                except Exception as e:
                    logger.error(f"Failed to translate speech: {e}")
            
            # Attach the updated task state to the response
            response.task_info = {
                "id": str(task.id),
                "workflow": task.workflow_id,
                "status": task.status,
                "step": task.current_step,
                "language": task.language
            }
            
            return response
