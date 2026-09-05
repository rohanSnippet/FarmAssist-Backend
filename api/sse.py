import queue

# A global dictionary mapping user_id -> list of queue.Queue
# This is a simple in-memory pub/sub mechanism for SSE.
active_streams = {}

def get_user_queues(user_id):
    return active_streams.get(user_id, [])

def add_stream(user_id, q):
    if user_id not in active_streams:
        active_streams[user_id] = []
    active_streams[user_id].append(q)

def remove_stream(user_id, q):
    if user_id in active_streams:
        try:
            active_streams[user_id].remove(q)
            if not active_streams[user_id]:
                del active_streams[user_id]
        except ValueError:
            pass

def push_event(user_id, event_data):
    """
    Pushes an event string to all active streams for a specific user.
    """
    queues = get_user_queues(user_id)
    for q in queues:
        try:
            q.put_nowait(event_data)
        except queue.Full:
            pass
