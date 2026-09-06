import redis
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

def get_redis_client():
    if not hasattr(settings, 'REDIS_URL') or not settings.REDIS_URL:
        logger.warning("REDIS_URL is not set. Real-time events may not work if running multiple workers.")
        return None
    try:
        return redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
    except Exception as e:
        logger.error(f"Failed to connect to Redis for SSE: {e}")
        return None

def push_event(user_id, event_data):
    """
    Pushes an event string to the Redis channel for a specific user.
    """
    client = get_redis_client()
    if client:
        try:
            channel = f"user_events_{user_id}"
            client.publish(channel, event_data)
        except Exception as e:
            logger.error(f"Error publishing SSE event to Redis: {e}")
