from __future__ import annotations

from collections import defaultdict
from threading import RLock

_locks: dict[int, RLock] = defaultdict(RLock)

def auction_lock(auction_id: int) -> RLock:
    """Process-local lock used to serialize state-changing auction actions.

    SQLite is used in the local V1. This lock prevents two nearly simultaneous
    bids/award actions from being accepted against the same stale current bid.
    When the app moves to multi-process hosting, this should be replaced by a
    database/distributed locking strategy.
    """
    return _locks[auction_id]
