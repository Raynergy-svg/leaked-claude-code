"""Session index — SQLite-backed fast lookup for session summaries.

Phase 4: Maintains a lightweight SQLite database at ``.aura/session_index.db``
with one row per session.  Supports upsert, query, listing (newest-first),
and deletion.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Optional

from src.aura.persistence.types import SessionSummary

logger = logging.getLogger(__name__)

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id     TEXT PRIMARY KEY,
    start_time     TEXT    NOT NULL,
    end_time       TEXT,
    message_count  INTEGER NOT NULL DEFAULT 0,
    readiness_start REAL,
    readiness_end   REAL,
    emotional_arc  TEXT    NOT NULL DEFAULT 'stable'
);
"""


class SessionIndex:
    """SQLite index of session summaries for fast lookup.

    Args:
        db_path: Path to the SQLite database file.  The parent directory
                 is created automatically if it does not exist.
                 Defaults to ``.aura/session_index.db``.
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._db_path = db_path or Path(".aura/session_index.db")
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute(_CREATE_TABLE_SQL)
        self._conn.commit()
        logger.debug("SessionIndex opened at %s", self._db_path)

    # -- mutations ----------------------------------------------------------

    def upsert_session(self, summary: SessionSummary) -> None:
        """Insert or update a session summary.

        Args:
            summary: The :class:`SessionSummary` to persist.
        """
        self._conn.execute(
            """
            INSERT INTO sessions
                (session_id, start_time, end_time, message_count,
                 readiness_start, readiness_end, emotional_arc)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                start_time      = excluded.start_time,
                end_time        = excluded.end_time,
                message_count   = excluded.message_count,
                readiness_start = excluded.readiness_start,
                readiness_end   = excluded.readiness_end,
                emotional_arc   = excluded.emotional_arc
            """,
            (
                summary.session_id,
                summary.start_time,
                summary.end_time,
                summary.message_count,
                summary.readiness_start,
                summary.readiness_end,
                summary.emotional_arc,
            ),
        )
        self._conn.commit()
        logger.debug("Upserted session %s", summary.session_id)

    def delete_session(self, session_id: str) -> None:
        """Remove a session from the index.

        Args:
            session_id: The conversation ID to delete.
        """
        self._conn.execute(
            "DELETE FROM sessions WHERE session_id = ?", (session_id,)
        )
        self._conn.commit()
        logger.debug("Deleted session %s", session_id)

    # -- queries ------------------------------------------------------------

    def get_session(self, session_id: str) -> Optional[SessionSummary]:
        """Retrieve a single session summary by ID.

        Args:
            session_id: The conversation ID to look up.

        Returns:
            A :class:`SessionSummary` or ``None`` if the session is not
            in the index.
        """
        row = self._conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_summary(row)

    def list_sessions(
        self, limit: int = 20, offset: int = 0
    ) -> list[SessionSummary]:
        """List session summaries, newest first.

        Args:
            limit: Maximum number of summaries to return.
            offset: Number of rows to skip (for pagination).

        Returns:
            A list of :class:`SessionSummary` ordered by ``start_time``
            descending.
        """
        rows = self._conn.execute(
            "SELECT * FROM sessions ORDER BY start_time DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [self._row_to_summary(r) for r in rows]

    # -- lifecycle ----------------------------------------------------------

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._conn.close()
        logger.debug("SessionIndex closed")

    # -- internal helpers ---------------------------------------------------

    @staticmethod
    def _row_to_summary(row: sqlite3.Row) -> SessionSummary:
        """Convert a sqlite3.Row to a SessionSummary dataclass."""
        return SessionSummary(
            session_id=row["session_id"],
            start_time=row["start_time"],
            end_time=row["end_time"],
            message_count=row["message_count"],
            readiness_start=row["readiness_start"],
            readiness_end=row["readiness_end"],
            emotional_arc=row["emotional_arc"],
        )
