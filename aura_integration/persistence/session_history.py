"""Session history — JSONL event log with cursor-based pagination.

Phase 4: Each session stores its events as one JSON object per line in
``.aura/history/{session_id}.jsonl``.  The writer appends atomically
using fcntl locks (falling back to direct append on platforms without
fcntl).  The reader supports cursor-based pagination for efficient
scrolling through long sessions.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from src.aura.persistence.types import HistoryPage, SessionEvent

logger = logging.getLogger(__name__)

# Check fcntl availability (not on Windows)
try:
    import fcntl

    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False


def _event_to_dict(event: SessionEvent) -> dict:
    """Serialize a SessionEvent to a plain dict."""
    return {
        "id": event.id,
        "type": event.type,
        "timestamp": event.timestamp,
        "session_id": event.session_id,
        "data": event.data,
    }


def _dict_to_event(d: dict) -> SessionEvent:
    """Deserialize a dict (from JSON) into a SessionEvent."""
    return SessionEvent(
        id=d["id"],
        type=d["type"],
        timestamp=d["timestamp"],
        session_id=d["session_id"],
        data=d.get("data", {}),
    )


class SessionHistoryWriter:
    """Appends events to per-session JSONL files with file locking.

    Args:
        history_dir: Directory where ``{session_id}.jsonl`` files are stored.
                     Defaults to ``.aura/history/``.
    """

    def __init__(self, history_dir: Optional[Path] = None) -> None:
        self._history_dir = history_dir or Path(".aura/history")
        self._history_dir.mkdir(parents=True, exist_ok=True)

    def session_file(self, session_id: str) -> Path:
        """Return the JSONL file path for a given session."""
        return self._history_dir / f"{session_id}.jsonl"

    def append_event(self, event: SessionEvent) -> None:
        """Append a single event as one JSONL line.

        Uses fcntl exclusive lock when available to prevent concurrent
        write corruption.  Falls back to direct append on Windows.

        Args:
            event: The SessionEvent to persist.
        """
        path = self.session_file(event.session_id)
        line = json.dumps(_event_to_dict(event), default=str) + "\n"

        path.parent.mkdir(parents=True, exist_ok=True)

        if _HAS_FCNTL:
            self._locked_append(path, line)
        else:
            self._direct_append(path, line)

        logger.debug("Appended event %s to %s", event.id, path)

    # -- internal helpers ---------------------------------------------------

    @staticmethod
    def _locked_append(path: Path, line: str) -> None:
        """Append with fcntl exclusive lock on a sidecar .lock file."""
        lock_path = Path(str(path) + ".lock")
        lock_fd = None
        try:
            lock_fd = open(lock_path, "w")
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)

            with open(path, "a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
        finally:
            if lock_fd is not None:
                try:
                    fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
                except (OSError, ValueError):
                    pass
                try:
                    lock_fd.close()
                except OSError:
                    pass

    @staticmethod
    def _direct_append(path: Path, line: str) -> None:
        """Append without locking (Windows fallback)."""
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()


class SessionHistoryReader:
    """Reads session events from JSONL files with cursor-based pagination.

    Args:
        history_dir: Directory where ``{session_id}.jsonl`` files are stored.
                     Defaults to ``.aura/history/``.
    """

    def __init__(self, history_dir: Optional[Path] = None) -> None:
        self._history_dir = history_dir or Path(".aura/history")

    def _read_all_events(self, session_id: str) -> list[SessionEvent]:
        """Read and parse all events from a session's JSONL file."""
        path = self._history_dir / f"{session_id}.jsonl"
        if not path.exists():
            return []

        events: list[SessionEvent] = []
        with open(path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    events.append(_dict_to_event(d))
                except (json.JSONDecodeError, KeyError) as exc:
                    logger.warning(
                        "Skipping malformed line %d in %s: %s", line_num, path, exc
                    )
        return events

    def fetch_latest(
        self, session_id: str, limit: int = 100
    ) -> HistoryPage:
        """Return the last *limit* events in chronological order.

        Args:
            session_id: The conversation ID to read.
            limit: Maximum number of events to return.

        Returns:
            A :class:`HistoryPage` with up to *limit* events, a cursor
            pointing at the first (oldest) event on the page, and a flag
            indicating whether older events exist.
        """
        all_events = self._read_all_events(session_id)
        if not all_events:
            return HistoryPage(events=[], first_id=None, has_more=False)

        page = all_events[-limit:]
        has_more = len(all_events) > limit
        first_id = page[0].id if page else None
        return HistoryPage(events=page, first_id=first_id, has_more=has_more)

    def fetch_older(
        self, session_id: str, before_id: str, limit: int = 100
    ) -> HistoryPage:
        """Return events older than *before_id* in chronological order.

        Args:
            session_id: The conversation ID to read.
            before_id: Event ID cursor — only events that appear *before*
                       this event in the log are considered.
            limit: Maximum number of events to return.

        Returns:
            A :class:`HistoryPage` of up to *limit* events preceding the
            cursor.
        """
        all_events = self._read_all_events(session_id)

        # Find the cursor index
        cursor_idx: Optional[int] = None
        for i, ev in enumerate(all_events):
            if ev.id == before_id:
                cursor_idx = i
                break

        if cursor_idx is None or cursor_idx == 0:
            return HistoryPage(events=[], first_id=None, has_more=False)

        # Slice the events before the cursor
        candidates = all_events[:cursor_idx]
        page = candidates[-limit:]
        has_more = len(candidates) > limit
        first_id = page[0].id if page else None
        return HistoryPage(events=page, first_id=first_id, has_more=has_more)

    def list_sessions(self) -> list[str]:
        """Return all session IDs found in the history directory.

        Session IDs are derived from JSONL filenames (without extension),
        sorted alphabetically.
        """
        if not self._history_dir.exists():
            return []

        return sorted(
            p.stem for p in self._history_dir.glob("*.jsonl") if p.is_file()
        )

    def count_events(self, session_id: str) -> int:
        """Return the total number of events in a session's log.

        Args:
            session_id: The conversation ID to count.
        """
        path = self._history_dir / f"{session_id}.jsonl"
        if not path.exists():
            return 0

        count = 0
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    count += 1
        return count
