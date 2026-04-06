"""Bounded UUID deduplication set for Aura message protocol.

Prevents echo loops in bidirectional transports by tracking recently-seen
message IDs.  Ported from the bounded UUID set in the TypeScript
structuredIO codebase (MAX_RESOLVED_TOOL_USE_IDS pattern).
"""

from __future__ import annotations

from collections import OrderedDict


class BoundedUUIDSet:
    """Track up to *max_size* recently-seen UUIDs with O(1) add/check.

    Uses an :class:`collections.OrderedDict` to maintain insertion order.
    When the set exceeds *max_size*, the oldest entry is automatically
    evicted, bounding memory in long-running sessions while retaining
    enough history to catch duplicate deliveries.

    Args:
        max_size: Maximum number of UUIDs to retain. Defaults to ``1000``.
    """

    def __init__(self, max_size: int = 1000) -> None:
        if max_size < 1:
            raise ValueError("max_size must be at least 1")
        self._max_size = max_size
        self._store: OrderedDict[str, None] = OrderedDict()

    @property
    def max_size(self) -> int:
        """Maximum number of entries before eviction."""
        return self._max_size

    def __len__(self) -> int:
        return len(self._store)

    def __contains__(self, uuid: str) -> bool:
        return uuid in self._store

    def add(self, uuid: str) -> bool:
        """Add a UUID to the set.

        If the UUID is already present, it is moved to the most-recent
        position (refreshed).  If the set is full, the oldest entry is
        evicted before insertion.

        Args:
            uuid: The UUID string to track.

        Returns:
            ``True`` if the UUID was already present (duplicate),
            ``False`` if it was newly added.
        """
        if uuid in self._store:
            # Refresh: move to end so it's treated as most-recent
            self._store.move_to_end(uuid)
            return True

        if len(self._store) >= self._max_size:
            # Evict oldest (first) entry
            self._store.popitem(last=False)

        self._store[uuid] = None
        return False

    def discard(self, uuid: str) -> None:
        """Remove a UUID from the set if present.

        Args:
            uuid: The UUID string to remove.
        """
        self._store.pop(uuid, None)

    def clear(self) -> None:
        """Remove all tracked UUIDs."""
        self._store.clear()
