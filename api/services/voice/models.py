from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Literal

@dataclass
class WorkflowEvent:
    """
    Standardized event payload received from the frontend or backend/Celery.
    """
    event_id: str
    event_type: str
    task_id: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    ui_context: Dict[str, Any] = field(default_factory=dict)

@dataclass
class AwaitingState:
    """
    Defines what the workflow is currently waiting for.
    """
    type: Literal["USER_INPUT", "APPLICATION_EVENT", "BACKEND_EVENT"]
    input: Optional[str] = None
    event: Optional[str] = None
    resource_id: Optional[Any] = None
    
    def to_dict(self):
        res = {"type": self.type}
        if self.input: res["input"] = self.input
        if self.event: res["event"] = self.event
        if self.resource_id: res["resource_id"] = self.resource_id
        return res

@dataclass
class WorkflowResponse:
    """
    The response sent back to the frontend.
    """
    task_info: Optional[Dict[str, Any]] = None
    speech: Optional[str] = None
    ui_action: Optional[Dict[str, Any]] = None
    awaiting: Optional[AwaitingState] = None
    
    def to_dict(self):
        res = {}
        if self.task_info: res["task"] = self.task_info
        if self.speech: res["speech"] = self.speech
        if self.ui_action: res["ui_action"] = self.ui_action
        if self.awaiting: res["awaiting"] = self.awaiting.to_dict()
        return res
