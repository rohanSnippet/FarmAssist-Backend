import os
import uuid
import json
from datetime import timedelta
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny
from livekit import api
from api.services.farmer_context_service import get_farmer_context_summary


class LiveKitTokenView(APIView):
    """
    POST /api/voice/token/ or GET /api/voice/token/

    Production-ready endpoint to generate short-lived LiveKit access tokens.
    Automatically assigns:
    - User identity & display name
    - Strictly isolated room name per farmer
    - Cryptographically signed farmer context metadata in JWT
    - Agent dispatch config for 'farmassist'
    """
    permission_classes = [AllowAny]

    def get_token(self, identity: str, room_name: str, agent_name: str = "farmassist", metadata: str = None) -> str:
        url = os.getenv("LIVEKIT_URL", "wss://farmassist-mitra-uf43lf3u.livekit.cloud")
        api_key = os.getenv("LIVEKIT_API_KEY", "API4es2ZyjHPrUY")
        api_secret = os.getenv("LIVEKIT_API_SECRET", "1TyejLkLDaNR0fzYSBzGxuCeL2neLD89KJTAM0aJRoOB")

        if not api_key or not api_secret:
            raise ValueError("LIVEKIT_API_KEY and LIVEKIT_API_SECRET must be configured in environment")

        token_builder = (
            api.AccessToken(api_key, api_secret)
            .with_identity(identity)
            .with_name(identity)
            .with_grants(api.VideoGrants(room_join=True, room=room_name))
            .with_room_config(
                api.RoomConfiguration(
                    agents=[api.RoomAgentDispatch(agent_name=agent_name)]
                )
            )
            .with_ttl(timedelta(hours=2))
        )

        if metadata:
            token_builder = token_builder.with_metadata(metadata)

        return token_builder.to_jwt()

    def post(self, request):
        user = request.user
        agent_name = request.data.get("agent_name", "farmassist")

        if user.is_authenticated:
            user_id = user.id
            identity = f"user_{user_id}"
            farmer_name = getattr(user, "first_name", "Farmer") or "Farmer"
            # Enforce room isolation: each farmer has private, non-colliding rooms
            requested_room = request.data.get("room")
            if requested_room and requested_room.startswith(f"farmassist-u{user_id}-"):
                room_name = requested_room
            else:
                room_name = f"farmassist-u{user_id}-{uuid.uuid4().hex[:8]}"

            farmer_context = get_farmer_context_summary(user)
        else:
            guest_id = uuid.uuid4().hex[:6]
            identity = f"guest_{guest_id}"
            farmer_name = "Farmer"
            room_name = f"farmassist-guest-{uuid.uuid4().hex[:8]}"
            farmer_context = get_farmer_context_summary(None)

        try:
            metadata_str = json.dumps(farmer_context)
            token = self.get_token(
                identity=identity,
                room_name=room_name,
                agent_name=agent_name,
                metadata=metadata_str
            )
            server_url = os.getenv("LIVEKIT_URL", "wss://farmassist-mitra-uf43lf3u.livekit.cloud")

            return Response({
                "status": "success",
                "token": token,
                "serverUrl": server_url,
                "room": room_name,
                "identity": identity,
                "farmerName": farmer_name,
                "agent": agent_name,
                "context": farmer_context
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({
                "status": "error",
                "message": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def get(self, request):
        """Allow simple GET request for dev testing."""
        return self.post(request)

