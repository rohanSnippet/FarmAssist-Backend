import logging
from .base import BaseWorkflow
from ..models import WorkflowEvent, WorkflowResponse, AwaitingState

logger = logging.getLogger(__name__)

class AddFarmWorkflow(BaseWorkflow):
    def process_event(self, event: WorkflowEvent) -> WorkflowResponse:
        """
        Manages the strict, UI-integrated ADD_FARM state machine.
        """
        if self.task.current_step == "START":
            self.task.current_step = "WAITING_FOR_CITY"
            
        elif self.task.current_step == "WAITING_FOR_CITY":
            if event.event_type == "USER_SPOKE":
                city = event.payload.get("extracted_entities", {}).get("location")
                if city:
                    self.update_data(city=city)
                    self.task.current_step = "WAITING_FOR_MAP_DRAW"
                
        elif self.task.current_step == "WAITING_FOR_MAP_DRAW":
            # The frontend should dispatch this when the user finishes drawing the polygon
            if event.event_type == "FARM_BOUNDARY_DRAWN":
                self.task.current_step = "WAITING_FOR_FARM_SAVE"
                
        elif self.task.current_step == "WAITING_FOR_FARM_SAVE":
            # The frontend dispatches FARM_SAVE_REQUESTED, but we only transition on FARM_CREATED (from DB/View)
            if event.event_type == "FARM_CREATED":
                farm_id = event.payload.get("farm_id")
                farm_name = event.payload.get("farm_name", "your new farm")
                self.update_data(farm_id=farm_id, farm_name=farm_name)
                self.task.current_step = "WAITING_FOR_CROP"
                
        elif self.task.current_step == "WAITING_FOR_CROP":
            if event.event_type == "USER_SPOKE":
                crop = event.payload.get("extracted_entities", {}).get("crop")
                if crop:
                    self.update_data(crop=crop)
                    self.task.current_step = "WAITING_FOR_PLANTING_DATE"
            elif event.event_type == "CROP_SELECTED":
                # Fallback if they clicked it in the UI
                crop = event.payload.get("crop")
                if crop:
                    self.update_data(crop=crop)
                    self.task.current_step = "WAITING_FOR_PLANTING_DATE"
                    
        elif self.task.current_step == "WAITING_FOR_PLANTING_DATE":
            if event.event_type == "USER_SPOKE":
                date = event.payload.get("extracted_entities", {}).get("planting_date")
                if date:
                    self.update_data(planting_date=date)
                    self.task.current_step = "WAITING_FOR_CROP_SAVE"
            elif event.event_type == "PLANTING_DATE_SELECTED":
                date = event.payload.get("planting_date")
                if date:
                    self.update_data(planting_date=date)
                    self.task.current_step = "WAITING_FOR_CROP_SAVE"
                    
        elif self.task.current_step == "WAITING_FOR_CROP_SAVE":
            if event.event_type == "CROP_CREATED" or event.event_type == "SEASON_CREATED":
                self.task.current_step = "COMPLETED"
                self.task.status = "COMPLETED"

        return self._build_response()
        
    def _build_response(self) -> WorkflowResponse:
        step = self.task.current_step
        d = self.task.collected_data
        
        if step == "WAITING_FOR_CITY":
            return WorkflowResponse(
                speech="Of course. I'll help you add it. Which city is your farm in?",
                ui_action={"type": "OPEN_NEW_FARM_MODAL"},
                awaiting=AwaitingState(type="USER_INPUT", input="CITY")
            )
        elif step == "WAITING_FOR_MAP_DRAW":
            city = d.get('city', 'your area')
            return WorkflowResponse(
                speech=f"Great. I've moved the map near {city}. Please move it to your exact farm location and tap Start Drawing. I'll stay with you while you mark the boundary.",
                ui_action={
                    "type": "MAP_FOCUS",
                    "location_hint": city
                },
                awaiting=AwaitingState(type="APPLICATION_EVENT", event="FARM_BOUNDARY_DRAWN")
            )
        elif step == "WAITING_FOR_FARM_SAVE":
            return WorkflowResponse(
                speech="Perfect. The boundary looks ready. Please tap Save Farm.",
                ui_action={
                    "type": "HIGHLIGHT_ELEMENT",
                    "target": "FARM_SAVE_BUTTON"
                },
                awaiting=AwaitingState(type="BACKEND_EVENT", event="FARM_CREATED")
            )
        elif step == "WAITING_FOR_CROP":
            return WorkflowResponse(
                speech="Excellent, your farm is registered. Now let's add the crop you're growing there. What crop are you planting?",
                ui_action={
                    "type": "OPEN_FARM",
                    "farm_id": d.get("farm_id")
                },
                awaiting=AwaitingState(type="USER_INPUT", input="CROP")
            )
        elif step == "WAITING_FOR_PLANTING_DATE":
            crop = d.get('crop', 'crop')
            return WorkflowResponse(
                speech=f"Got it, {crop}. When did you start cultivating this {crop}?",
                ui_action={
                    "type": "SET_FORM_VALUE",
                    "field": "crop",
                    "value": crop
                },
                awaiting=AwaitingState(type="USER_INPUT", input="PLANTING_DATE")
            )
        elif step == "WAITING_FOR_CROP_SAVE":
            return WorkflowResponse(
                speech="I have filled in the planting date. Please tap Save to register your crop.",
                ui_action={
                    "type": "HIGHLIGHT_ELEMENT",
                    "target": "CROP_SAVE_BUTTON"
                },
                awaiting=AwaitingState(type="BACKEND_EVENT", event="CROP_CREATED")
            )
        elif step == "COMPLETED":
            return WorkflowResponse(
                speech="Your crop has been registered. I can now help you monitor it, detect pests and diseases, and give stage-based guidance."
            )
            
        # Fallback for old/legacy states from before the architecture update
        logger.warning(f"Unknown state '{step}', resetting ADD_FARM workflow.")
        self.task.current_step = "WAITING_FOR_CITY"
        return self._build_response()
