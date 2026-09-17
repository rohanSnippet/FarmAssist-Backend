from django.core.cache import cache
import uuid

# Expiration time for a conversation context in seconds (e.g., 5 minutes)
SESSION_TTL = 300

def get_or_create_session(user_id: int, session_id: str = None) -> tuple[str, dict]:
    """
    Retrieves an existing voice session or creates a new one.
    Returns (session_id, context_dict).
    """
    if not session_id:
        session_id = f"voice_session_{user_id}_{uuid.uuid4().hex[:8]}"
        context = {}
        _save_session(session_id, context)
        return session_id, context
        
    cache_key = f"voice_session_{session_id}"
    context = cache.get(cache_key)
    
    if context is None:
        # Session expired or invalid; create a new one
        session_id = f"voice_session_{user_id}_{uuid.uuid4().hex[:8]}"
        context = {}
        _save_session(session_id, context)
        
    return session_id, context

def update_session(session_id: str, new_data: dict) -> dict:
    """
    Updates the existing session with new data and refreshes TTL.
    """
    cache_key = f"voice_session_{session_id}"
    context = cache.get(cache_key) or {}
    context.update(new_data)
    _save_session(session_id, context)
    return context

def _save_session(session_id: str, context: dict):
    cache_key = f"voice_session_{session_id}"
    cache.set(cache_key, context, timeout=SESSION_TTL)
