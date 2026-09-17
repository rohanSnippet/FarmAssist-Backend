from typing import Dict, Type
from .workflows.base import BaseWorkflow
from .workflows.add_farm import AddFarmWorkflow
from .workflows.crop_scan import CropScanWorkflow
from .workflows.one_shot import FarmOverviewWorkflow, StageAdvisoryWorkflow, CropQuestionWorkflow

# Map of workflow IDs to their implementing classes
WORKFLOW_REGISTRY: Dict[str, Type[BaseWorkflow]] = {
    "ADD_FARM": AddFarmWorkflow,
    "CROP_SCAN": CropScanWorkflow,
    "FARM_OVERVIEW": FarmOverviewWorkflow,
    "STAGE_ADVISORY": StageAdvisoryWorkflow,
    "CROP_QUESTION": CropQuestionWorkflow
}

def get_workflow_class(workflow_id: str) -> Type[BaseWorkflow]:
    if workflow_id not in WORKFLOW_REGISTRY:
        raise ValueError(f"Unknown workflow ID: {workflow_id}")
    return WORKFLOW_REGISTRY[workflow_id]
