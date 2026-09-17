import logging
from .base import BaseWorkflow
from ..models import WorkflowEvent, WorkflowResponse, AwaitingState
from api.models import CropScanJob

logger = logging.getLogger(__name__)

class CropScanWorkflow(BaseWorkflow):
    def process_event(self, event: WorkflowEvent) -> WorkflowResponse:
        """
        Manages the CROP_SCAN state machine.
        """
        if self.task.current_step == "START":
            # Extract initial data
            extracted = event.payload.get("extracted_entities", {})
            self.update_data(**extracted)
            self.task.current_step = self._get_next_missing_step()
            
        elif self.task.current_step == "WAITING_FOR_FARM":
            if event.event_type == "USER_SPOKE":
                # Assuming the intent resolver validates this
                farm_id = event.payload.get("resolved_farm_id")
                if farm_id:
                    self.update_data(farm_id=farm_id)
                    self.task.current_step = self._get_next_missing_step()
                    
        elif self.task.current_step == "WAITING_FOR_IMAGE":
            if event.event_type == "SCAN_SUBMITTED":
                scan_job_id = event.payload.get("scan_job_id")
                if scan_job_id:
                    self.update_data(scan_job_id=scan_job_id)
                    self.transition("WAITING_FOR_CELERY", status="WAITING_FOR_BACKEND")
                    
        elif self.task.current_step == "WAITING_FOR_CELERY":
            if event.event_type == "SCAN_STATUS_CHANGED":
                # Check backend authoritative status
                scan_job_id = self.task.collected_data.get("scan_job_id")
                try:
                    job = CropScanJob.objects.get(id=scan_job_id)
                    if job.status == CropScanJob.Status.COMPLETED:
                        self.transition("LOAD_RESULT", status="COMPLETED")
                    elif job.status == CropScanJob.Status.FAILED:
                        self.transition("FAILED", status="FAILED")
                    # If still PENDING/PROCESSING, do nothing and keep waiting
                except CropScanJob.DoesNotExist:
                    self.transition("FAILED", status="FAILED")

        return self._build_response()
        
    def _get_next_missing_step(self):
        d = self.task.collected_data
        if not d.get("farm_id"): return "WAITING_FOR_FARM"
        # We can also add RESOLVE_CROP, RESOLVE_SEASON here if needed.
        return "WAITING_FOR_IMAGE"

    def _build_response(self) -> WorkflowResponse:
        step = self.task.current_step
        d = self.task.collected_data
        
        if step == "WAITING_FOR_FARM":
            return WorkflowResponse(
                speech="Which farm is this for?",
                awaiting=AwaitingState(type="USER_INPUT", input="FARM_SELECTION")
            )
        elif step == "WAITING_FOR_IMAGE":
            return WorkflowResponse(
                speech="Please click the camera button to take a photo of the affected crop leaf so I can analyze the disease.",
                ui_action={"type": "OPEN_SCANNER"},
                awaiting=AwaitingState(type="APPLICATION_EVENT", event="SCAN_SUBMITTED")
            )
        elif step == "WAITING_FOR_CELERY":
            return WorkflowResponse(
                speech="I've started analyzing the image. Please wait a moment.",
                awaiting=AwaitingState(type="BACKEND_EVENT", event="SCAN_COMPLETED", resource_id=d.get("scan_job_id"))
            )
        elif step == "LOAD_RESULT":
            # Fetch actual result
            try:
                job = CropScanJob.objects.get(id=d.get("scan_job_id"))
                # primary_diagnosis is the top-level field set by the AI pipeline
                diagnosis = job.result.get('primary_diagnosis', 'an unknown condition')
                crop = job.result.get('crop', 'your crop')
                confidence = job.result.get('confidence', 0)
                conf_pct = int(confidence * 100) if confidence <= 1 else int(confidence)
                speech = (
                    f"The scan is complete. It looks like {crop} might be affected by "
                    f"{diagnosis} with {conf_pct}% confidence. Check the app for full treatment advice."
                )
            except Exception:
                speech = "The scan is complete, but I couldn't read the result."
                
            return WorkflowResponse(speech=speech)
            
        elif step == "FAILED":
            return WorkflowResponse(speech="I'm sorry, there was a problem analyzing the scan. Please try again.")
            
        return WorkflowResponse(speech="I'm not sure what to do next.")
