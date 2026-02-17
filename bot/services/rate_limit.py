from __future__ import annotations

import time
from collections import defaultdict, deque

_events: dict[str, deque[float]] = defaultdict(deque)


def is_allowed(user_id: int, action: str, limit: int, window_sec: int) -> bool:
    if limit <= 0 or window_sec <= 0:
        return True
    now = time.time()
    key = f"{action}:{user_id}"
    bucket = _events[key]
    cutoff = now - window_sec
    while bucket and bucket[0] < cutoff:
        bucket.popleft()
    if len(bucket) >= limit:
        return False
    bucket.append(now)
    return True
