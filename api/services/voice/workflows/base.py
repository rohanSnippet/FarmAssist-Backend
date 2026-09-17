from abc import ABC, abstractmethod
from typing import Dict, Any, Tuple
from ..models import WorkflowEvent, WorkflowResponse

class BaseWorkflow(ABC):
    """
    Abstract base class for all voice workflows.
    """
    
    def __init__(self, task):
        # task is a VoiceTask model instance
        self.task = task

    @abstractmethod
    def process_event(self, event: WorkflowEvent) -> WorkflowResponse:
        """
        Process the incoming event and return the response to the user.
        Must mutate self.task (e.g. self.task.status, self.task.current_step, self.task.collected_data) as needed.
        The WorkflowEngine will handle saving the task to the database.
        """
        pass
    
    def update_data(self, **kwargs):
        """Helper to update collected_data"""
        if not self.task.collected_data:
            self.task.collected_data = {}
        self.task.collected_data.update(kwargs)

    def transition(self, step: str, status: str = None):
        """Helper to transition to a new step/status"""
        self.task.current_step = step
        if status:
            self.task.status = status
