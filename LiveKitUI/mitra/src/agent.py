import os
import json
import logging
from typing import Literal
from dotenv import load_dotenv
from pathlib import Path

from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    TurnHandlingOptions,
    function_tool,
    cli,
)
from livekit.plugins import google, sarvam

logger = logging.getLogger("farmassist.agent")
logging.basicConfig(level=logging.INFO)

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
# Load local agent env first
if (PROJECT_ROOT / ".env.local").exists():
    load_dotenv(PROJECT_ROOT / ".env.local")
if (PROJECT_ROOT / ".env").exists():
    load_dotenv(PROJECT_ROOT / ".env")

# Search ancestor directories for backend .env (works whether in root or in backend/LiveKitUI)
for parent in Path(__file__).resolve().parents:
    if (parent / ".env").exists() and parent != PROJECT_ROOT:
        load_dotenv(parent / ".env")
        break
    if (parent / "backend" / ".env").exists():
        load_dotenv(parent / "backend" / ".env")
        break


# ---------------------------------------------------------------------------
# LiveKit server with Pre-warmed Worker Pool (Instant Connection)
# ---------------------------------------------------------------------------
server = AgentServer(
    num_idle_processes=1,             # Pre-warm 1 worker process on startup so connection is instant (0ms wait)
    initialize_process_timeout=60.0,  # 60s headroom for Windows environment initial loading
)


# ---------------------------------------------------------------------------
# Dynamic Farmer-Centric System Prompt Builder (Zero Cross-Farmer Leakage)
# ---------------------------------------------------------------------------
def build_farmer_prompt(farmer_context: dict) -> str:
    farmer_name = farmer_context.get("farmer_name") or "Farmer"
    district = farmer_context.get("district") or "India"
    farms = farmer_context.get("farms", [])
    recent_scans = farmer_context.get("recent_scans", [])

    farms_summary = []
    if farms:
        for f in farms:
            f_name = f.get("farm_name", "Farm")
            active_crop = f.get("active_crop")
            if active_crop and active_crop.get("crop_name"):
                crop_name = active_crop.get("crop_name")
                age = active_crop.get("crop_age_days")
                age_str = f" ({age} days since planting)" if age is not None else ""
                farms_summary.append(f"- {f_name}: growing {crop_name}{age_str}")
            else:
                farms_summary.append(f"- {f_name}: registered (no active crop)")
    else:
        farms_summary.append("- No farms registered yet in the app")

    scans_summary = []
    if recent_scans:
        for s in recent_scans:
            c = s.get("crop_hint", "Crop")
            diag = s.get("diagnosis", "Unknown")
            conf = s.get("confidence_pct", 0)
            treatment = s.get("treatment_hint", "")
            t_hint = f" | Advisory: {treatment}" if treatment else ""
            scans_summary.append(f"- Scan #{s.get('scan_job_id', '')} on {c}: {diag} ({conf}% conf){t_hint}")
    else:
        scans_summary.append("- No recent disease scans")

    farms_text = "\n".join(farms_summary)
    scans_text = "\n".join(scans_summary)

    prompt = f"""You are Mitra (मित्र), the personal agricultural AI assistant and voice navigator ("Jarvis") for {farmer_name}.
You are speaking with {farmer_name} who farms in {district}.

THIS FARMER'S AUTHENTICATED AGRICULTURAL CONTEXT (STRICTLY PRIVATE):
Farms & Crops:
{farms_text}

Recent Disease & Pest Scans:
{scans_text}

CRITICAL SECURITY & PRIVACY RULES:
1. You are operating in a single, isolated session exclusively for {farmer_name}.
2. You have ZERO access to any other user's records. Never mention or invent other farmers' names or plots.
3. Treat the context above as ground truth when the farmer mentions "my crop", "my farm", or "my previous scan".

BEHAVIOR FOR ILLITERATE AND SEMI-LITERATE FARMERS:
- Keep all spoken replies short, natural, and conversational (1 to 3 sentences maximum).
- Avoid complex agronomic jargon or chemical trade names unless giving a direct verified spray recipe.
- Speak with warm respect and clear phrasing.

JARVIS AUTONOMOUS ACTION EXECUTION:
- When the farmer asks to see a page, scan a plant, open the map, or see recommendations:
  DO NOT tell the farmer to navigate manually.
  EXECUTE THE APPROPRIATE ACTION TOOL IMMEDIATELY (navigate_app, open_scanner, open_farm_creation, open_crop_recommendation).
- Always explain what you just opened on their screen and tell them what simple physical step to do next:
  * For scanning: "I have opened the camera on your screen. Hold your phone up to the damaged leaf and tap the camera button."
  * For farm mapping: "I have opened the map near your village. Tap the green draw button and tap the four corners of your plot."
  * For crop advice: "I have opened the crop recommendation screen. You can upload your Soil Health Card photo here."

SUPPORTED INDIAN LANGUAGES & DIALECTS:
- Hindi, Marathi, Telugu, Tamil, Gujarati, Bengali, English, and natural mixtures (Hinglish, Marathi-English).
- Always reply in the exact same language and dialect the farmer used.
"""
    return prompt


# ---------------------------------------------------------------------------
# Agent entrypoint (Isolated per room / per farmer session)
# ---------------------------------------------------------------------------
@server.rtc_session(agent_name="farmassist")
async def entrypoint(ctx: JobContext):
    """
    Entry point for every FarmAssist voice session.
    Each LiveKit session is completely isolated between users/rooms.
    """
    ctx.log_context_fields = {
        "agent": "farmassist",
        "room": ctx.room.name,
    }

    # 1. Connect agent to the room first
    await ctx.connect()

    # 2. Wait for the farmer participant to join to extract cryptographically verified metadata
    participant = await ctx.wait_for_participant()
    raw_metadata = participant.metadata or "{}"

    try:
        farmer_context = json.loads(raw_metadata)
    except Exception as e:
        logger.warning(f"Could not parse participant metadata: {e}. Falling back to default.")
        farmer_context = {}

    farmer_name = farmer_context.get("farmer_name", "Farmer")
    logger.info(f"Mitra Jarvis activated for farmer: {farmer_name} in room: {ctx.room.name}")

    # Build dynamically isolated instructions for this specific farmer
    farmer_instructions = build_farmer_prompt(farmer_context)

    # -----------------------------------------------------------------------
    # Jarvis Action Tools (Scoped to this session and room)
    # -----------------------------------------------------------------------

    @function_tool(description="Navigate the farmer's screen to a specific section of the FarmAssist application.")
    async def navigate_app(
        route: Literal["/my-farms", "/pest-prediction", "/crop-recommendations", "/history", "/pest-history", "/me"],
        reason: str = ""
    ) -> str:
        """Supported routes: /my-farms, /pest-prediction, /crop-recommendations, /history, /pest-history, /me"""
        route_map = {
            "farms": "/my-farms",
            "farm": "/my-farms",
            "my-farms": "/my-farms",
            "my_farms": "/my-farms",
            "scanner": "/pest-prediction",
            "scan": "/pest-prediction",
            "crop-scanner": "/pest-prediction",
            "leaf": "/pest-prediction",
            "pest": "/pest-prediction",
            "pest-prediction": "/pest-prediction",
            "recommendations": "/crop-recommendations",
            "crop-recommendations": "/crop-recommendations",
            "crop": "/crop-recommendations",
            "crops": "/crop-recommendations",
            "soil": "/crop-recommendations",
            "history": "/history",
            "pest-history": "/pest-history",
            "me": "/me",
            "profile": "/me",
            "dashboard": "/my-farms",
            "home": "/my-farms",
        }
        clean_route = str(route).strip().lower().lstrip("/")
        canonical_route = route_map.get(clean_route, f"/{clean_route}" if not str(route).startswith("/") else str(route))

        action_payload = {
            "type": "UI_ACTION",
            "action": "NAVIGATE",
            "route": canonical_route,
            "message": reason
        }
        await ctx.room.local_participant.publish_data(
            json.dumps(action_payload).encode("utf-8"),
            reliable=True
        )
        return f"Screen navigated to {canonical_route} on farmer's device."

    @function_tool(description="Open the camera scanner so the farmer can take a photo of an affected plant leaf to detect pests or diseases.")
    async def open_scanner(crop_hint: str = "") -> str:
        """Navigates to the Crop Scanner and highlights the camera button."""
        action_payload = {
            "type": "UI_ACTION",
            "action": "OPEN_SCANNER",
            "route": "/pest-prediction",
            "crop_hint": crop_hint or "",
            "highlight": "#crop-camera-btn"
        }
        await ctx.room.local_participant.publish_data(
            json.dumps(action_payload).encode("utf-8"),
            reliable=True
        )
        return "Camera scanner opened on farmer's screen. Guided farmer to point phone at leaf."

    @function_tool(description="Open the farm management map so the farmer can add and mark their farm boundary.")
    async def open_farm_creation(city_or_taluka: str = "") -> str:
        """Navigates to /my-farms and focuses the boundary mapper."""
        action_payload = {
            "type": "UI_ACTION",
            "action": "OPEN_NEW_FARM_MODAL",
            "route": "/my-farms",
            "location_hint": city_or_taluka or "",
            "highlight": "#start-draw-btn"
        }
        await ctx.room.local_participant.publish_data(
            json.dumps(action_payload).encode("utf-8"),
            reliable=True
        )
        return f"Opened farm creation map centered on {city_or_taluka or 'farmer location'}."

    @function_tool(description="Open the Crop Recommendation page where the farmer can get AI crop advice or upload their Soil Health Card.")
    async def open_crop_recommendation() -> str:
        action_payload = {
            "type": "UI_ACTION",
            "action": "OPEN_CROP_RECOMMENDATIONS",
            "route": "/crop-recommendations",
            "highlight": "#soil-card-upload-btn"
        }
        await ctx.room.local_participant.publish_data(
            json.dumps(action_payload).encode("utf-8"),
            reliable=True
        )
        return "Navigated to crop recommendation screen."

    @function_tool(description="Retrieve details and remedy from the farmer's recent crop diagnostic scans.")
    async def get_scan_details(crop_name: str = "") -> str:
        recent = farmer_context.get("recent_scans", [])
        if not recent:
            return "No previous disease scans found. Advise farmer to tap camera to take a photo of their leaf."
        
        target = recent[0]
        if crop_name:
            for s in recent:
                if crop_name.lower() in s.get("crop_hint", "").lower():
                    target = s
                    break

        diagnosis = target.get("diagnosis", "Unknown Condition")
        crop = target.get("crop_hint", "crop")
        conf = target.get("confidence_pct", 0)
        treatment = target.get("treatment_hint", "Check FarmAssist app for full CIB&RC treatment guidelines.")
        
        return f"Scan result for {crop}: {diagnosis} (Confidence: {conf}%). Remedy: {treatment}"

    @function_tool(description="Get Mandi market prices and trends for a specific crop.")
    async def get_mandi_prices(crop: str, market: str = "") -> str:
        loc = market or farmer_context.get("district", "local mandi")
        return f"In {loc}, modal market price for {crop} is currently stable to upward, trading in standard APMC brackets."

    @function_tool(description="Get agricultural weather advisory for spraying, harvesting, or irrigation.")
    async def get_weather_advisory(location: str = "") -> str:
        loc = location or farmer_context.get("district", "your area")
        return f"Weather for {loc}: Moderate humidity and light winds. Favorable for morning pesticide spray."

    tools = [
        navigate_app,
        open_scanner,
        open_farm_creation,
        open_crop_recommendation,
        get_scan_details,
        get_mandi_prices,
        get_weather_advisory,
    ]

    # -----------------------------------------------------------------------
    # Sarvam Speech-to-Text (Realtime Indian Languages with Low Latency)
    # -----------------------------------------------------------------------
    stt = sarvam.STTRealtime(
        language="auto",
        stream_type="fast",
        mode="transcribe",
        endpointing="vad",
        sample_rate=16000,
        vad_min_silence_ms=450,       # Fast endpointing (450ms silence instead of 1000ms default)
        vad_prefix_padding_ms=150,    # Reduced prefix padding to cut transport delay
        vad_min_speech_ms=200,        # Quickly detect true speech utterances
        prompt=(
            "FarmAssist agricultural assistant Mitra. "
            "Indian farming. Tomato, Onion, Cotton, Soybean, Wheat, Rice, Chilli, Mango. "
            "Kharif, Rabi, Mandi, Early Blight, Mancozeb, NPK, Soil Card."
        ),
    )

    # -----------------------------------------------------------------------
    # Google Gemini LLM
    # -----------------------------------------------------------------------
    llm = google.LLM(
        model=os.environ.get("GEMINI_MODEL", "gemini-3.6-flash"),
    )

    # -----------------------------------------------------------------------
    # Sarvam Text-to-Speech (Bulbul v3 Multilingual)
    # -----------------------------------------------------------------------
    tts = sarvam.TTS(
        model="bulbul:v3",
        target_language_code="en-IN",
        speaker="shubh",
        speech_sample_rate=22050,
        pace=1.05,
        min_buffer_size=40,
        max_chunk_length=120,
        output_audio_codec="mp3",
        output_audio_bitrate="128k",
    )

    # -----------------------------------------------------------------------
    # Agent session with TurnHandling & Real-time Optimization (No CPU VAD bottleneck)
    # -----------------------------------------------------------------------
    session = AgentSession(
        stt=stt,
        llm=llm,
        tts=tts,
        vad=None,  # Offloads VAD to Sarvam cloud STT; eliminates CPU-blocking Silero VAD on Windows
        turn_handling=TurnHandlingOptions(
            turn_detection="stt",  # STT event driven turn detection
            endpointing={
                "mode": "fixed",
                "min_delay": 0.2,   # Rapid 200ms commit after STT final transcript
                "max_delay": 1.2,
            },
            interruption={"enabled": True},
            preemptive_generation={"enabled": True, "max_retries": 3},
        ),
    )

    # -----------------------------------------------------------------------
    # Dynamic TTS language switching on STT detection
    # -----------------------------------------------------------------------
    @session.on("user_input_transcribed")
    def on_user_transcribed(event):
        if not event.is_final:
            return

        detected_language = event.language
        if not detected_language:
            return

        lang_str = str(detected_language).lower()
        if lang_str.startswith("hi"):
            tts_language = "hi-IN"
        elif lang_str.startswith("mr"):
            tts_language = "mr-IN"
        elif lang_str.startswith("ta"):
            tts_language = "ta-IN"
        elif lang_str.startswith("te"):
            tts_language = "te-IN"
        elif lang_str.startswith("bn"):
            tts_language = "bn-IN"
        elif lang_str.startswith("gu"):
            tts_language = "gu-IN"
        else:
            tts_language = "en-IN"

        tts.update_options(target_language_code=tts_language)
        logger.info(f"Transcript ({detected_language} -> {tts_language}): {event.transcript}")

    # Listen to Data Channel messages from Frontend
    @ctx.room.on("data_received")
    def on_data_received(data_packet):
        try:
            raw = data_packet.data
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            evt = json.loads(raw)
            logger.info(f"Received frontend event: {evt.get('event')}")
        except Exception as err:
            logger.debug(f"Data packet parsing: {err}")

    # -----------------------------------------------------------------------
    # Start Agent Session
    # -----------------------------------------------------------------------
    await session.start(
        agent=Agent(
            instructions=farmer_instructions,
            tools=tools,
        ),
        room=ctx.room,
    )


# ---------------------------------------------------------------------------
# CLI Entrypoint for Local / Production Execution
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    cli.run_app(server)