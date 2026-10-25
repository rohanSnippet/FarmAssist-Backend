import json
import jwt
from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import Polygon
from api.models import Farm, FarmSeason, CropScanJob
from api.voice_api.views import LiveKitTokenView
from api.services.farmer_context_service import get_farmer_context_summary

User = get_user_model()

class VoiceSecurityAndContextTestCase(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        
        # Create Farmer 1 (Ramesh)
        self.farmer1 = User.objects.create_user(
            email="ramesh@test.com",
            first_name="Ramesh",
            location_label="Nashik, Maharashtra"
        )
        # Create Farm for Ramesh
        self.poly1 = Polygon(((0, 0), (0, 1), (1, 1), (1, 0), (0, 0)))
        self.farm1 = Farm.objects.create(
            user=self.farmer1,
            name="Ganga Farm",
            boundaries=self.poly1
        )
        self.season1 = FarmSeason.objects.create(
            farm=self.farm1,
            crop_name="Tomato",
            is_active=True
        )
        self.scan1 = CropScanJob.objects.create(
            user=self.farmer1,
            crop_hint="Tomato",
            status=CropScanJob.Status.COMPLETED,
            image_data=b"dummy_image",
            result={"primary_diagnosis": "Early Blight", "confidence": 0.91}
        )

        # Create Farmer 2 (Suresh)
        self.farmer2 = User.objects.create_user(
            email="suresh@test.com",
            first_name="Suresh",
            location_label="Pune, Maharashtra"
        )
        self.poly2 = Polygon(((2, 2), (2, 3), (3, 3), (3, 2), (2, 2)))
        self.farm2 = Farm.objects.create(
            user=self.farmer2,
            name="Mula Plot",
            boundaries=self.poly2
        )

    def test_farmer_context_isolation(self):
        """Verify get_farmer_context_summary strictly isolates context between farmers."""
        ctx1 = get_farmer_context_summary(self.farmer1)
        ctx2 = get_farmer_context_summary(self.farmer2)

        self.assertEqual(ctx1["farmer_name"], "Ramesh")
        self.assertEqual(ctx1["user_id"], self.farmer1.id)
        self.assertEqual(len(ctx1["farms"]), 1)
        self.assertEqual(ctx1["farms"][0]["farm_name"], "Ganga Farm")
        self.assertEqual(ctx1["farms"][0]["active_crop"]["crop_name"], "Tomato")
        self.assertEqual(len(ctx1["recent_scans"]), 1)
        self.assertEqual(ctx1["recent_scans"][0]["diagnosis"], "Early Blight")

        # Farmer 2 must NOT see Farmer 1's farm or scans
        self.assertEqual(ctx2["farmer_name"], "Suresh")
        self.assertEqual(ctx2["user_id"], self.farmer2.id)
        self.assertEqual(len(ctx2["farms"]), 1)
        self.assertEqual(ctx2["farms"][0]["farm_name"], "Mula Plot")
        self.assertEqual(len(ctx2["recent_scans"]), 0)

    def test_token_view_embeds_signed_metadata_and_isolates_room(self):
        """Verify LiveKitTokenView embeds signed metadata and generates isolated room."""
        view = LiveKitTokenView.as_view()
        request = self.factory.post('/api/voice/token/', {}, content_type='application/json')
        request.user = self.farmer1

        response = view(request)
        self.assertEqual(response.status_code, 200)
        data = response.data
        self.assertTrue(data["room"].startswith(f"farmassist-u{self.farmer1.id}-"))
        self.assertEqual(data["identity"], f"user_{self.farmer1.id}")
        self.assertEqual(data["farmerName"], "Ramesh")

        # Decode token claims to verify metadata is embedded in JWT
        decoded = jwt.decode(data["token"], options={"verify_signature": False})
        self.assertIn("metadata", decoded)
        metadata = json.loads(decoded["metadata"])
        self.assertEqual(metadata["farmer_name"], "Ramesh")
        self.assertEqual(metadata["user_id"], self.farmer1.id)
        self.assertEqual(metadata["farms"][0]["farm_name"], "Ganga Farm")

    def test_prevent_cross_user_room_hijacking(self):
        """Farmer 2 cannot hijack Farmer 1's room."""
        view = LiveKitTokenView.as_view()
        # Farmer 2 tries to join a room belonging to Farmer 1
        hijack_attempt = {
            "room": f"farmassist-u{self.farmer1.id}-secretroom"
        }
        request = self.factory.post('/api/voice/token/', hijack_attempt, content_type='application/json')
        request.user = self.farmer2

        response = view(request)
        self.assertEqual(response.status_code, 200)
        # Server must override and force a room scoped to farmer2
        self.assertTrue(response.data["room"].startswith(f"farmassist-u{self.farmer2.id}-"))
        self.assertFalse(response.data["room"].startswith(f"farmassist-u{self.farmer1.id}-"))

    def test_anonymous_user_safe_fallback(self):
        """Unauthenticated user receives guest room and empty context."""
        view = LiveKitTokenView.as_view()
        request = self.factory.post('/api/voice/token/', {}, content_type='application/json')
        from django.contrib.auth.models import AnonymousUser
        request.user = AnonymousUser()

        response = view(request)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["room"].startswith("farmassist-guest-"))
        self.assertEqual(response.data["farmerName"], "Farmer")
        self.assertEqual(response.data["context"]["farms"], [])
        self.assertEqual(response.data["context"]["recent_scans"], [])
