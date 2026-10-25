import os
from dotenv import load_dotenv

from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    cli,
    inference,
)

from livekit.plugins import sarvam


# ---------------------------------------------------------
# Environment
# ---------------------------------------------------------

load_dotenv(".env.local")

server = AgentServer()


# ---------------------------------------------------------
# FarmAssist instructions
# ---------------------------------------------------------

FARMASSIST_INSTRUCTIONS = """
You are FarmAssist, a voice-first agricultural assistant.

Your primary users are farmers in India.

SUPPORTED LANGUAGES:
- English
- Hindi
- Marathi
- Tamil
- Telugu

LANGUAGE BEHAVIOR:
1. Always understand the language used by the farmer.
2. Reply in the same language the farmer used.
3. If the farmer switches languages, immediately follow the new language.
4. Hindi and Marathi may both use Devanagari script. Do not confuse them.
   Use the language detected by the speech recognition system as the primary
   language signal.
5. English, Hindi, Marathi, Tamil and Telugu may be mixed naturally.
6. If the farmer uses Hinglish, respond naturally in Hinglish.
7. If the farmer uses Marathi mixed with English, respond naturally in
   Marathi-English.
8. Do not translate the farmer's request into English unless explicitly asked.

VOICE BEHAVIOR:
- Keep responses short and conversational.
- Speak naturally.
- Do not give long paragraphs unless the farmer asks for details.
- For simple requests, answer in 1-3 sentences.
- If an action is required, acknowledge it briefly and perform the action.
- Never expose internal tool names or implementation details.

FARMASSIST ROLE:
You help farmers with:
- crop recommendations
- crop prediction
- disease detection
- weather
- fertilizer recommendations
- farming information
- agricultural schemes
- market information
- navigating the FarmAssist application

APPLICATION BEHAVIOR:
FarmAssist will have tools for application navigation and backend operations.
When an appropriate tool is available, use the tool instead of merely
describing what the farmer should do.

IMPORTANT:
Do not pretend that an application action was completed if the corresponding
tool has not actually completed it.
"""


# ---------------------------------------------------------
# Realtime Agent
# ---------------------------------------------------------

@server.rtc_session(agent_name="farmassist")
async def entrypoint(ctx: JobContext):

    ctx.log_context_fields = {
        "agent": "farmassist",
        "room": ctx.room.name,
    }

    # -----------------------------------------------------
    # Multilingual realtime STT
    #
    # Sarvam:
    #   saaras:v3-realtime
    #
    # language="auto":
    #   Hindi
    #   Marathi
    #   English
    #   Tamil
    #   Telugu
    #
    # stream_type="fast":
    #   prioritize low latency partial transcripts
    # -----------------------------------------------------

    stt = sarvam.STTRealtime(
        language="auto",
        stream_type="fast",
        mode="transcribe",
        endpointing="vad",
        sample_rate=16000,

        # FarmAssist-specific vocabulary/context.
        prompt=(
            "FarmAssist agricultural assistant. "
            "Indian farming. "
            "Crops, soil, fertilizer, disease, weather, rainfall, "
            "nitrogen, phosphorus, potassium, pH, market prices, "
            "crop prediction, disease detection."
        ),
    )

    # -----------------------------------------------------
    # Fast LLM
    #
    # Use LiveKit Inference so the agent infrastructure and
    # model communication remain close to LiveKit.
    # -----------------------------------------------------

    llm = inference.LLM(
        model="google/gemini-3.1-flash-lite",
        extra_kwargs={
            "max_completion_tokens": 500,
        },
    )

    # -----------------------------------------------------
    # Multilingual TTS
    #
    # Start with Sarvam Bulbul v3.
    #
    # It supports Indian-language speech and lets us change
    # target_language_code at runtime.
    # -----------------------------------------------------

    tts = sarvam.TTS(
        model="bulbul:v3",
        target_language_code="en-IN",
        speaker="shubh",

        # 22.05 kHz is recommended for general voice agents.
        speech_sample_rate=22050,

        # Keep speech reasonably quick.
        pace=1.05,

        # Smaller buffers improve perceived latency.
        min_buffer_size=50,
        max_chunk_length=150,

        output_audio_codec="mp3",
        output_audio_bitrate="128k",
    )

    # -----------------------------------------------------
    # Agent session
    # -----------------------------------------------------

    session = AgentSession(
        stt=stt,
        llm=llm,
        tts=tts,

        # Let the user interrupt the assistant.
        allow_interruptions=True,

        # Start generating before the exact end-of-turn when
        # possible to reduce perceived latency.
        preemptive_generation=True,
    )

    # -----------------------------------------------------
    # Detect language from STT and change TTS language
    # -----------------------------------------------------

    @session.on("user_input_transcribed")
    def on_user_transcribed(event):

        if not event.is_final:
            return

        detected_language = event.language

        if detected_language is None:
            return

        language = str(detected_language).lower()

        # Normalize detected language to Sarvam TTS codes.
        if language.startswith("hi"):
            tts_language = "hi-IN"

        elif language.startswith("mr"):
            tts_language = "mr-IN"

        elif language.startswith("ta"):
            tts_language = "ta-IN"

        elif language.startswith("te"):
            tts_language = "te-IN"

        elif language.startswith("en"):
            tts_language = "en-IN"

        else:
            # Safety fallback.
            tts_language = "en-IN"

        # Change the language used by the next TTS response.
        tts.update_options(
            target_language_code=tts_language
        )

        print(
            f"[FarmAssist] "
            f"language={detected_language} "
            f"tts={tts_language} "
            f"text={event.transcript}"
        )

    # -----------------------------------------------------
    # Start
    # -----------------------------------------------------

    await session.start(
        agent=Agent(
            instructions=FARMASSIST_INSTRUCTIONS,
        ),
        room=ctx.room,
    )

    await ctx.connect()


# ---------------------------------------------------------
# Run
# ---------------------------------------------------------

if __name__ == "__main__":
    cli.run_app(server)
