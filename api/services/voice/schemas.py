from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict

@dataclass
class UIAction:
    type: str
    params: Dict[str, Any]

@dataclass
class ResponsePlan:
    speech: str
    ui_action: UIAction
    next_state: str
    session_id: str
    language_code: str
    
    def to_dict(self) -> dict:
        return {
            "speech": self.speech,
            "ui_action": {
                "type": self.ui_action.type,
                "params": self.ui_action.params
            },
            "next_state": self.next_state,
            "session_id": self.session_id,
            "language_code": self.language_code,
            "executed": True
        }

@dataclass
class StructuredAdvisory:
    schema_version: int = 1
    agricultural_context: dict = None
    diagnosis: str = "Unknown"
    treatment_candidates: list = None
    
    def to_dict(self) -> dict:
        return asdict(self)
