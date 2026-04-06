"""Persistence data types for session history and indexing.

Phase 4: Defines the core data structures used by SessionHistoryWriter,
SessionHistoryReader, and SessionIndex.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SessionEvent:
    """A single event in a session's history log.

    Attributes:
        id: UUID string identifying this event.
        type: Event kind — one of ``"user_message"``, ``"aura_response"``,
              ``"readiness_update"``, ``"signal_snapshot"``.
        timestamp: ISO 8601 timestamp of when the event occurred.
        session_id: The conversation ID this event belongs to.
        data: Arbitrary payload dict (message text, score, signals, etc.).
    """

    id: str
    type: str
    timestamp: str
    session_id: str
    data: dict = field(default_factory=dict)


@dataclass
class HistoryPage:
    """A page of session events returned by cursor-based pagination.

    Attributes:
        events: The events on this page, in chronological order.
        first_id: Cursor pointing to the oldest event on this page,
                  or ``None`` if the page is empty.  Pass this value as
                  ``before_id`` to :meth:`SessionHistoryReader.fetch_older`
                  to retrieve the preceding page.
        has_more: Whether older events exist beyond this page.
    """

    events: list[SessionEvent]
    first_id: Optional[str]
    has_more: bool


@dataclass
class SessionSummary:
    """Aggregate summary of a single session, stored in the SQLite index.

    Attributes:
        session_id: The conversation ID.
        start_time: ISO 8601 timestamp of session start.
        end_time: ISO 8601 timestamp of session end, or ``None`` if ongoing.
        message_count: Total number of user + assistant messages.
        readiness_start: Readiness score at the beginning, or ``None``.
        readiness_end: Readiness score at the end, or ``None``.
        emotional_arc: High-level trajectory — one of ``"stable"``,
                       ``"declining"``, ``"improving"``, ``"volatile"``.
    """

    session_id: str
    start_time: str
    end_time: Optional[str] = None
    message_count: int = 0
    readiness_start: Optional[float] = None
    readiness_end: Optional[float] = None
    emotional_arc: str = "stable"
