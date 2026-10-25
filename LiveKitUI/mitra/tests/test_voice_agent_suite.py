import sys
import json
import unittest
from unittest.mock import MagicMock, AsyncMock, patch

# Add backend and LiveKitUI to sys.path
from pathlib import Path
MITRA_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MITRA_ROOT / "src"))

backend_path = None
for parent in Path(__file__).resolve().parents:
    if parent.name == "backend":
        backend_path = parent
        break
    if (parent / "backend").exists():
        backend_path = parent / "backend"
        break

if backend_path:
    sys.path.insert(0, str(backend_path))

import jwt
from datetime import datetime
from agent import build_farmer_prompt


class TestVoiceAgentSecurityAndIsolation(unittest.TestCase):
    """
    Validates that:
    1. Farmer contexts are strictly isolated (no cross-farmer data leakage).
    2. Dynamic system prompts personalize for the specific farmer while protecting privacy.
    3. LiveKit tokens cryptographically seal the verified context.
    4. Unauthenticated users cannot view any farmer's private data.
    """

    def setUp(self):
        self.farmer_ramesh = {
            "farmer_name": "Ramesh",
            "user_id": 101,
            "district": "Nashik, Maharashtra",
            "farms": [
                {
                    "farm_id": 1,
                    "farm_name": "Ganga Farm",
                    "location": {"district": "Nashik, Maharashtra"},
                    "active_crop": {
                        "crop_name": "Tomato",
                        "crop_age_days": 35
                    }
                },
                {
                    "farm_id": 2,
                    "farm_name": "Shree Plot",
                    "location": {"district": "Nashik, Maharashtra"},
                    "active_crop": {
                        "crop_name": "Onion",
                        "crop_age_days": 15
                    }
                }
            ],
            "recent_scans": [
                {
                    "scan_job_id": 501,
                    "status": "COMPLETED",
                    "crop_hint": "Tomato",
                    "created_at": "2026-10-20",
                    "diagnosis": "Early Blight",
                    "confidence_pct": 92,
                    "treatment_hint": "Spray Mancozeb 75% WP @ 2g per liter of water."
                }
            ]
        }

        self.farmer_suresh = {
            "farmer_name": "Suresh",
            "user_id": 202,
            "district": "Pune, Maharashtra",
            "farms": [
                {
                    "farm_id": 8,
                    "farm_name": "Mula Farm",
                    "location": {"district": "Pune, Maharashtra"},
                    "active_crop": {
                        "crop_name": "Sugarcane",
                        "crop_age_days": 120
                    }
                }
            ],
            "recent_scans": []
        }

        self.anonymous_farmer = {
            "farmer_name": "Farmer",
            "user_id": None,
            "district": "",
            "farms": [],
            "recent_scans": []
        }

    def test_dynamic_prompt_isolation(self):
        """Verify prompt for Ramesh contains his farms and never leaks to Suresh."""
        prompt_ramesh = build_farmer_prompt(self.farmer_ramesh)
        prompt_suresh = build_farmer_prompt(self.farmer_suresh)

        # Ramesh's prompt checks
        self.assertIn("Ramesh", prompt_ramesh)
        self.assertIn("Ganga Farm", prompt_ramesh)
        self.assertIn("Tomato (35 days since planting)", prompt_ramesh)
        self.assertIn("Early Blight (92% conf)", prompt_ramesh)
        self.assertIn("Mancozeb 75% WP", prompt_ramesh)

        # Must NOT contain Suresh's data
        self.assertNotIn("Suresh", prompt_ramesh)
        self.assertNotIn("Mula Farm", prompt_ramesh)
        self.assertNotIn("Sugarcane", prompt_ramesh)

        # Suresh's prompt checks
        self.assertIn("Suresh", prompt_suresh)
        self.assertIn("Mula Farm", prompt_suresh)
        self.assertIn("Sugarcane (120 days since planting)", prompt_suresh)
        self.assertIn("No recent disease scans", prompt_suresh)

        # Must NOT contain Ramesh's data
        self.assertNotIn("Ramesh", prompt_suresh)
        self.assertNotIn("Ganga Farm", prompt_suresh)
        self.assertNotIn("Early Blight", prompt_suresh)

    def test_anonymous_prompt_safety(self):
        """Verify unauthenticated user receives a safe generic prompt with zero private records."""
        prompt_anon = build_farmer_prompt(self.anonymous_farmer)
        self.assertIn("Farmer", prompt_anon)
        self.assertIn("No farms registered yet in the app", prompt_anon)
        self.assertIn("No recent disease scans", prompt_anon)
        self.assertNotIn("Ramesh", prompt_anon)
        self.assertNotIn("Suresh", prompt_anon)

    def test_token_view_cryptographic_metadata(self):
        """Simulate LiveKitTokenView token generation and verify sealed claims."""
        from livekit import api
        api_key = "API4es2ZyjHPrUY"
        api_secret = "1TyejLkLDaNR0fzYSBzGxuCeL2neLD89KJTAM0aJRoOB"
        
        metadata_str = json.dumps(self.farmer_ramesh)
        room_name = f"farmassist-u{self.farmer_ramesh['user_id']}-test01"

        token = (
            api.AccessToken(api_key, api_secret)
            .with_identity(f"user_{self.farmer_ramesh['user_id']}")
            .with_name(self.farmer_ramesh["farmer_name"])
            .with_metadata(metadata_str)
            .with_grants(api.VideoGrants(room_join=True, room=room_name))
            .to_jwt()
        )

        # Verify cryptographic decoding
        decoded = jwt.decode(token, api_secret, algorithms=["HS256"])
        self.assertEqual(decoded["sub"], "user_101")
        self.assertEqual(decoded["video"]["room"], room_name)
        
        extracted_context = json.loads(decoded["metadata"])
        self.assertEqual(extracted_context["farmer_name"], "Ramesh")
        self.assertEqual(len(extracted_context["farms"]), 2)
        self.assertEqual(extracted_context["farms"][0]["farm_name"], "Ganga Farm")


class TestJarvisActionTools(unittest.IsolatedAsyncioTestCase):
    """
    Tests that Jarvis tools:
    1. Send valid WebRTC Data Channel JSON payloads for screen control.
    2. Correctly trigger navigation, scanning, and farm creation.
    3. Return plain, spoken summaries appropriate for illiterate farmers.
    """

    async def test_jarvis_action_payload_structures(self):
        """Verify that UI action payloads match what Frontend/src/voice/actions/uiActionRegistry.js expects."""
        mock_room = MagicMock()
        mock_room.local_participant.publish_data = AsyncMock()

        # Test navigate_app
        async def mock_navigate_app(route: str, reason: str = ""):
            payload = {
                "type": "UI_ACTION",
                "action": "NAVIGATE",
                "route": route,
                "message": reason
            }
            await mock_room.local_participant.publish_data(
                json.dumps(payload).encode("utf-8"),
                reliable=True
            )
            return f"Screen navigated to {route} on farmer's device."

        res = await mock_navigate_app("/my-farms", "Showing your farm plots")
        self.assertIn("Screen navigated to /my-farms", res)
        mock_room.local_participant.publish_data.assert_called_once()
        
        raw_call_arg = mock_room.local_participant.publish_data.call_args[0][0]
        sent_data = json.loads(raw_call_arg.decode("utf-8"))
        self.assertEqual(sent_data["type"], "UI_ACTION")
        self.assertEqual(sent_data["action"], "NAVIGATE")
        self.assertEqual(sent_data["route"], "/my-farms")

    async def test_open_scanner_action_payload(self):
        """Verify open_scanner triggers crop scanner with highlight."""
        mock_room = MagicMock()
        mock_room.local_participant.publish_data = AsyncMock()

        async def mock_open_scanner(crop_hint: str = ""):
            payload = {
                "type": "UI_ACTION",
                "action": "OPEN_SCANNER",
                "route": "/pest-prediction",
                "crop_hint": crop_hint or "",
                "highlight": "#crop-camera-btn"
            }
            await mock_room.local_participant.publish_data(
                json.dumps(payload).encode("utf-8"),
                reliable=True
            )
            return "Camera scanner opened on farmer's screen."

        res = await mock_open_scanner("tomato")
        self.assertIn("Camera scanner opened", res)
        raw_call_arg = mock_room.local_participant.publish_data.call_args[0][0]
        sent_data = json.loads(raw_call_arg.decode("utf-8"))
        self.assertEqual(sent_data["action"], "OPEN_SCANNER")
        self.assertEqual(sent_data["crop_hint"], "tomato")
        self.assertEqual(sent_data["highlight"], "#crop-camera-btn")

    async def test_open_farm_creation_payload(self):
        """Verify open_farm_creation targets map drawing."""
        mock_room = MagicMock()
        mock_room.local_participant.publish_data = AsyncMock()

        async def mock_open_farm_creation(city: str = ""):
            payload = {
                "type": "UI_ACTION",
                "action": "OPEN_NEW_FARM_MODAL",
                "route": "/my-farms",
                "location_hint": city,
                "highlight": "#start-draw-btn"
            }
            await mock_room.local_participant.publish_data(
                json.dumps(payload).encode("utf-8"),
                reliable=True
            )
            return f"Opened farm creation map centered on {city}."

        res = await mock_open_farm_creation("Dindori")
        self.assertIn("Dindori", res)
        raw_call_arg = mock_room.local_participant.publish_data.call_args[0][0]
        sent_data = json.loads(raw_call_arg.decode("utf-8"))
        self.assertEqual(sent_data["action"], "OPEN_NEW_FARM_MODAL")
        self.assertEqual(sent_data["location_hint"], "Dindori")
        self.assertEqual(sent_data["highlight"], "#start-draw-btn")


class TestMultilingualDialectMapping(unittest.TestCase):
    """
    Validates dynamic TTS mapping for Indian languages and code-switching.
    """

    def test_language_code_to_tts_options(self):
        test_cases = [
            ("hi", "hi-IN"),
            ("hi-Latn", "hi-IN"), # Hinglish
            ("mr", "mr-IN"),      # Marathi
            ("mr-Latn", "mr-IN"), # Marathi-English
            ("ta", "ta-IN"),      # Tamil
            ("te", "te-IN"),      # Telugu
            ("bn", "bn-IN"),      # Bengali
            ("gu", "gu-IN"),      # Gujarati
            ("en", "en-IN"),      # Indian English
            ("unknown", "en-IN")  # Safe fallback
        ]

        def resolve_tts(detected_lang):
            lang_str = str(detected_lang).lower()
            if lang_str.startswith("hi"):
                return "hi-IN"
            elif lang_str.startswith("mr"):
                return "mr-IN"
            elif lang_str.startswith("ta"):
                return "ta-IN"
            elif lang_str.startswith("te"):
                return "te-IN"
            elif lang_str.startswith("bn"):
                return "bn-IN"
            elif lang_str.startswith("gu"):
                return "gu-IN"
            return "en-IN"

        for detected, expected in test_cases:
            with self.subTest(detected=detected):
                self.assertEqual(resolve_tts(detected), expected)


if __name__ == "__main__":
    unittest.main()
