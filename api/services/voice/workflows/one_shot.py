import logging
from .base import BaseWorkflow
from ..models import WorkflowEvent, WorkflowResponse

logger = logging.getLogger(__name__)

class FarmOverviewWorkflow(BaseWorkflow):
    def process_event(self, event: WorkflowEvent) -> WorkflowResponse:
        # A one-shot workflow.
        try:
            farms = self.task.user.farms.all()
            count = farms.count()
            if count == 0:
                speech = "You don't have any farms registered yet."
            elif count == 1:
                speech = f"You have one farm registered: {farms.first().name}."
            else:
                speech = f"You have {count} farms registered."
        except Exception:
            speech = "I couldn't retrieve your farm information."
            
        self.transition("COMPLETE", status="COMPLETED")
        return WorkflowResponse(speech=speech)

class StageAdvisoryWorkflow(BaseWorkflow):
    def process_event(self, event: WorkflowEvent) -> WorkflowResponse:
        speech = "I'm looking up the advisory for that stage..."
        self.transition("COMPLETE", status="COMPLETED")
        return WorkflowResponse(speech=speech)

class CropQuestionWorkflow(BaseWorkflow):
    def process_event(self, event: WorkflowEvent) -> WorkflowResponse:
        speech = "Let me check the agricultural knowledge base for that."
        self.transition("COMPLETE", status="COMPLETED")
        return WorkflowResponse(speech=speech)
