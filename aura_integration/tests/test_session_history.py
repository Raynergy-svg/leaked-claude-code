"""Tests for Phase 4 session history persistence.

Covers SessionEvent, SessionHistoryWriter, SessionHistoryReader,
SessionIndex, and integration scenarios with cursor-based pagination.
"""

import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from aura.persistence.types import SessionEvent, HistoryPage, SessionSummary
from aura.persistence.session_history import (
    SessionHistoryWriter,
    SessionHistoryReader,
    _event_to_dict,
    _dict_to_event,
)
from aura.persistence.session_index import SessionIndex


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(
    session_id: str = "conv_20260406_100000",
    event_type: str = "user_message",
    data: dict | None = None,
    event_id: str | None = None,
    timestamp: str | None = None,
) -> SessionEvent:
    """Create a SessionEvent with sensible defaults."""
    return SessionEvent(
        id=event_id or str(uuid.uuid4()),
        type=event_type,
        timestamp=timestamp or datetime.now(timezone.utc).isoformat(),
        session_id=session_id,
        data=data or {"content": "test message"},
    )


def _make_events(n: int, session_id: str = "conv_20260406_100000") -> list[SessionEvent]:
    """Create *n* numbered events with stable, sequential IDs."""
    events = []
    for i in range(n):
        events.append(
            SessionEvent(
                id=f"evt_{i:04d}",
                type="user_message" if i % 2 == 0 else "aura_response",
                timestamp=f"2026-04-06T10:{i // 60:02d}:{i % 60:02d}Z",
                session_id=session_id,
                data={"seq": i},
            )
        )
    return events


def _make_summary(
    session_id: str = "conv_20260406_100000",
    start_time: str = "2026-04-06T10:00:00Z",
    **kwargs,
) -> SessionSummary:
    """Create a SessionSummary with sensible defaults."""
    return SessionSummary(session_id=session_id, start_time=start_time, **kwargs)


# ===========================================================================
# SessionEvent tests
# ===========================================================================

class TestSessionEvent:
    """SessionEvent dataclass behaviour."""

    def test_create_event_all_fields(self):
        """Create event and verify every field is stored."""
        ev = SessionEvent(
            id="abc-123",
            type="user_message",
            timestamp="2026-04-06T10:00:00Z",
            session_id="conv_20260406_100000",
            data={"content": "feeling great"},
        )
        assert ev.id == "abc-123"
        assert ev.type == "user_message"
        assert ev.timestamp == "2026-04-06T10:00:00Z"
        assert ev.session_id == "conv_20260406_100000"
        assert ev.data == {"content": "feeling great"}

    def test_default_data_is_empty_dict(self):
        """data defaults to {} when omitted."""
        ev = SessionEvent(
            id="x", type="readiness_update",
            timestamp="t", session_id="s",
        )
        assert ev.data == {}

    def test_serialize_to_dict_and_back(self):
        """Round-trip through _event_to_dict / _dict_to_event."""
        original = _make_event(data={"score": 0.87, "note": "focused"})
        d = _event_to_dict(original)
        restored = _dict_to_event(d)

        assert restored.id == original.id
        assert restored.type == original.type
        assert restored.timestamp == original.timestamp
        assert restored.session_id == original.session_id
        assert restored.data == original.data

    def test_serialize_through_json(self):
        """Round-trip through actual JSON serialization."""
        original = _make_event(data={"nested": {"a": [1, 2, 3]}})
        json_str = json.dumps(_event_to_dict(original))
        restored = _dict_to_event(json.loads(json_str))
        assert restored.data == original.data

    @pytest.mark.parametrize("event_type", [
        "user_message",
        "aura_response",
        "readiness_update",
        "signal_snapshot",
    ])
    def test_different_event_types(self, event_type):
        """All four documented event types are accepted."""
        ev = _make_event(event_type=event_type)
        assert ev.type == event_type

    def test_dict_missing_data_key_defaults_empty(self):
        """_dict_to_event handles dicts with no 'data' key."""
        d = {
            "id": "x",
            "type": "user_message",
            "timestamp": "t",
            "session_id": "s",
        }
        ev = _dict_to_event(d)
        assert ev.data == {}


# ===========================================================================
# HistoryPage / SessionSummary dataclass smoke tests
# ===========================================================================

class TestHistoryPage:
    """HistoryPage dataclass basics."""

    def test_empty_page(self):
        page = HistoryPage(events=[], first_id=None, has_more=False)
        assert page.events == []
        assert page.first_id is None
        assert page.has_more is False

    def test_page_with_events(self):
        evts = _make_events(3)
        page = HistoryPage(events=evts, first_id=evts[0].id, has_more=True)
        assert len(page.events) == 3
        assert page.has_more is True


class TestSessionSummary:
    """SessionSummary dataclass defaults."""

    def test_defaults(self):
        s = SessionSummary(session_id="s1", start_time="t1")
        assert s.end_time is None
        assert s.message_count == 0
        assert s.readiness_start is None
        assert s.readiness_end is None
        assert s.emotional_arc == "stable"

    def test_full_construction(self):
        s = SessionSummary(
            session_id="s1", start_time="t1", end_time="t2",
            message_count=42, readiness_start=0.5, readiness_end=0.9,
            emotional_arc="improving",
        )
        assert s.message_count == 42
        assert s.emotional_arc == "improving"


# ===========================================================================
# SessionHistoryWriter tests
# ===========================================================================

class TestSessionHistoryWriter:
    """SessionHistoryWriter — JSONL append behaviour."""

    def test_write_creates_file(self, tmp_path):
        """Appending an event creates the JSONL file."""
        writer = SessionHistoryWriter(history_dir=tmp_path)
        ev = _make_event(session_id="sess_1")
        writer.append_event(ev)

        path = tmp_path / "sess_1.jsonl"
        assert path.exists()

    def test_file_format_is_valid_jsonl(self, tmp_path):
        """Each line is valid JSON."""
        writer = SessionHistoryWriter(history_dir=tmp_path)
        for i in range(5):
            writer.append_event(_make_event(session_id="sess_jsonl", event_id=f"e{i}"))

        path = tmp_path / "sess_jsonl.jsonl"
        lines = path.read_text().strip().splitlines()
        assert len(lines) == 5
        for line in lines:
            obj = json.loads(line)  # must not raise
            assert "id" in obj
            assert "type" in obj

    def test_multiple_events_append(self, tmp_path):
        """Events accumulate, one per line."""
        writer = SessionHistoryWriter(history_dir=tmp_path)
        events = _make_events(10, session_id="sess_append")
        for ev in events:
            writer.append_event(ev)

        path = tmp_path / "sess_append.jsonl"
        lines = [l for l in path.read_text().splitlines() if l.strip()]
        assert len(lines) == 10

        # Verify order is preserved
        ids = [json.loads(l)["id"] for l in lines]
        assert ids == [ev.id for ev in events]

    def test_session_file_path(self, tmp_path):
        """session_file() returns the correct path."""
        writer = SessionHistoryWriter(history_dir=tmp_path)
        assert writer.session_file("conv_123") == tmp_path / "conv_123.jsonl"

    def test_separate_sessions_separate_files(self, tmp_path):
        """Events for different sessions go to different files."""
        writer = SessionHistoryWriter(history_dir=tmp_path)
        writer.append_event(_make_event(session_id="alpha"))
        writer.append_event(_make_event(session_id="beta"))

        assert (tmp_path / "alpha.jsonl").exists()
        assert (tmp_path / "beta.jsonl").exists()

    def test_data_preserved_in_jsonl(self, tmp_path):
        """Complex data payloads survive serialization."""
        writer = SessionHistoryWriter(history_dir=tmp_path)
        ev = _make_event(
            session_id="sess_data",
            data={"score": 0.75, "signals": {"stress": 0.3}, "tags": ["focused"]},
        )
        writer.append_event(ev)

        line = (tmp_path / "sess_data.jsonl").read_text().strip()
        obj = json.loads(line)
        assert obj["data"]["score"] == 0.75
        assert obj["data"]["signals"]["stress"] == 0.3
        assert obj["data"]["tags"] == ["focused"]


# ===========================================================================
# SessionHistoryReader tests
# ===========================================================================

class TestSessionHistoryReader:
    """SessionHistoryReader — cursor-based pagination."""

    @pytest.fixture()
    def populated_history(self, tmp_path):
        """Write 20 events and return (reader, events, session_id)."""
        session_id = "sess_read"
        events = _make_events(20, session_id=session_id)
        writer = SessionHistoryWriter(history_dir=tmp_path)
        for ev in events:
            writer.append_event(ev)
        reader = SessionHistoryReader(history_dir=tmp_path)
        return reader, events, session_id

    # -- fetch_latest -------------------------------------------------------

    def test_fetch_latest_chronological_order(self, populated_history):
        """fetch_latest returns events in chronological order."""
        reader, events, sid = populated_history
        page = reader.fetch_latest(sid)
        assert [e.id for e in page.events] == [e.id for e in events]

    def test_fetch_latest_with_limit(self, populated_history):
        """fetch_latest(limit=5) returns the last 5 events."""
        reader, events, sid = populated_history
        page = reader.fetch_latest(sid, limit=5)
        assert len(page.events) == 5
        assert [e.id for e in page.events] == [e.id for e in events[-5:]]

    def test_fetch_latest_has_more_true(self, populated_history):
        """has_more=True when more events exist beyond the page."""
        reader, _, sid = populated_history
        page = reader.fetch_latest(sid, limit=5)
        assert page.has_more is True

    def test_fetch_latest_has_more_false_when_all_fit(self, populated_history):
        """has_more=False when all events fit in one page."""
        reader, _, sid = populated_history
        page = reader.fetch_latest(sid, limit=100)
        assert page.has_more is False

    def test_fetch_latest_first_id_cursor(self, populated_history):
        """first_id points to the oldest event on the page."""
        reader, events, sid = populated_history
        page = reader.fetch_latest(sid, limit=5)
        assert page.first_id == events[-5].id

    def test_fetch_latest_empty_session(self, tmp_path):
        """Empty/missing session returns empty page."""
        reader = SessionHistoryReader(history_dir=tmp_path)
        page = reader.fetch_latest("nonexistent")
        assert page.events == []
        assert page.first_id is None
        assert page.has_more is False

    # -- fetch_older --------------------------------------------------------

    def test_fetch_older_paginates_correctly(self, populated_history):
        """fetch_older with before_id returns events before that cursor."""
        reader, events, sid = populated_history
        # Get last 5
        page1 = reader.fetch_latest(sid, limit=5)
        # Get the 5 before those
        page2 = reader.fetch_older(sid, before_id=page1.first_id, limit=5)
        assert len(page2.events) == 5
        assert [e.id for e in page2.events] == [e.id for e in events[-10:-5]]

    def test_fetch_older_has_more_false_on_last_page(self, populated_history):
        """has_more=False when we reach the beginning."""
        reader, events, sid = populated_history
        # Fetch older starting from event index 3 (only 3 events before it)
        page = reader.fetch_older(sid, before_id=events[3].id, limit=100)
        assert len(page.events) == 3
        assert page.has_more is False

    def test_fetch_older_has_more_true_when_more_exist(self, populated_history):
        """has_more=True when events exist before the page."""
        reader, events, sid = populated_history
        # Cursor at event 10, limit 5 -> events 5..9, more before
        page = reader.fetch_older(sid, before_id=events[10].id, limit=5)
        assert len(page.events) == 5
        assert page.has_more is True

    def test_fetch_older_unknown_cursor_returns_empty(self, populated_history):
        """Unknown before_id returns empty page."""
        reader, _, sid = populated_history
        page = reader.fetch_older(sid, before_id="nonexistent_id", limit=10)
        assert page.events == []
        assert page.has_more is False

    def test_fetch_older_first_event_returns_empty(self, populated_history):
        """Cursor at the very first event returns empty (nothing before it)."""
        reader, events, sid = populated_history
        page = reader.fetch_older(sid, before_id=events[0].id, limit=10)
        assert page.events == []
        assert page.has_more is False

    # -- list_sessions ------------------------------------------------------

    def test_list_sessions(self, tmp_path):
        """list_sessions returns all session IDs."""
        writer = SessionHistoryWriter(history_dir=tmp_path)
        writer.append_event(_make_event(session_id="alpha"))
        writer.append_event(_make_event(session_id="beta"))
        writer.append_event(_make_event(session_id="gamma"))

        reader = SessionHistoryReader(history_dir=tmp_path)
        sessions = reader.list_sessions()
        assert sorted(sessions) == ["alpha", "beta", "gamma"]

    def test_list_sessions_empty_dir(self, tmp_path):
        """list_sessions returns empty list when no sessions exist."""
        reader = SessionHistoryReader(history_dir=tmp_path)
        assert reader.list_sessions() == []

    def test_list_sessions_nonexistent_dir(self, tmp_path):
        """list_sessions returns empty list for missing directory."""
        reader = SessionHistoryReader(history_dir=tmp_path / "nope")
        assert reader.list_sessions() == []

    # -- count_events -------------------------------------------------------

    def test_count_events(self, populated_history):
        """count_events returns the correct total."""
        reader, _, sid = populated_history
        assert reader.count_events(sid) == 20

    def test_count_events_empty(self, tmp_path):
        """count_events returns 0 for nonexistent session."""
        reader = SessionHistoryReader(history_dir=tmp_path)
        assert reader.count_events("ghost") == 0

    # -- malformed data resilience ------------------------------------------

    def test_skips_malformed_lines(self, tmp_path):
        """Malformed JSON lines are skipped, valid lines are returned."""
        session_id = "sess_bad"
        path = tmp_path / f"{session_id}.jsonl"
        good_event = _make_event(session_id=session_id, event_id="good_1")
        good_line = json.dumps(_event_to_dict(good_event))
        path.write_text(f"{good_line}\nNOT VALID JSON\n{good_line}\n")

        reader = SessionHistoryReader(history_dir=tmp_path)
        page = reader.fetch_latest(session_id)
        assert len(page.events) == 2

    def test_skips_blank_lines(self, tmp_path):
        """Blank lines in JSONL are ignored."""
        session_id = "sess_blank"
        path = tmp_path / f"{session_id}.jsonl"
        ev = _make_event(session_id=session_id, event_id="e1")
        line = json.dumps(_event_to_dict(ev))
        path.write_text(f"\n{line}\n\n{line}\n\n")

        reader = SessionHistoryReader(history_dir=tmp_path)
        assert reader.count_events(session_id) == 2


# ===========================================================================
# SessionIndex tests
# ===========================================================================

class TestSessionIndex:
    """SessionIndex — SQLite-backed session summaries."""

    @pytest.fixture()
    def index(self, tmp_path):
        """Create a SessionIndex in a temp directory."""
        idx = SessionIndex(db_path=tmp_path / "test_index.db")
        yield idx
        idx.close()

    def test_upsert_creates_new(self, index):
        """upsert_session creates a new entry."""
        summary = _make_summary(session_id="s1")
        index.upsert_session(summary)
        result = index.get_session("s1")
        assert result is not None
        assert result.session_id == "s1"
        assert result.start_time == "2026-04-06T10:00:00Z"

    def test_upsert_updates_existing(self, index):
        """upsert_session updates fields of an existing entry."""
        index.upsert_session(_make_summary(session_id="s1", message_count=5))
        index.upsert_session(_make_summary(session_id="s1", message_count=15, end_time="t2"))
        result = index.get_session("s1")
        assert result.message_count == 15
        assert result.end_time == "t2"

    def test_get_session_unknown_returns_none(self, index):
        """get_session returns None for unknown session."""
        assert index.get_session("nonexistent") is None

    def test_list_sessions_newest_first(self, index):
        """list_sessions returns sessions ordered by start_time desc."""
        index.upsert_session(_make_summary("s_old", start_time="2026-04-01T00:00:00Z"))
        index.upsert_session(_make_summary("s_mid", start_time="2026-04-03T00:00:00Z"))
        index.upsert_session(_make_summary("s_new", start_time="2026-04-06T00:00:00Z"))

        results = index.list_sessions()
        ids = [r.session_id for r in results]
        assert ids == ["s_new", "s_mid", "s_old"]

    def test_list_sessions_limit(self, index):
        """list_sessions respects limit."""
        for i in range(10):
            index.upsert_session(
                _make_summary(f"s_{i:02d}", start_time=f"2026-04-{i + 1:02d}T00:00:00Z")
            )
        results = index.list_sessions(limit=3)
        assert len(results) == 3

    def test_list_sessions_offset(self, index):
        """list_sessions respects offset for pagination."""
        for i in range(5):
            index.upsert_session(
                _make_summary(f"s_{i}", start_time=f"2026-04-{i + 1:02d}T00:00:00Z")
            )
        page1 = index.list_sessions(limit=2, offset=0)
        page2 = index.list_sessions(limit=2, offset=2)
        # No overlap
        ids1 = {r.session_id for r in page1}
        ids2 = {r.session_id for r in page2}
        assert ids1.isdisjoint(ids2)
        assert len(page2) == 2

    def test_delete_session(self, index):
        """delete_session removes the entry."""
        index.upsert_session(_make_summary("doomed"))
        assert index.get_session("doomed") is not None
        index.delete_session("doomed")
        assert index.get_session("doomed") is None

    def test_delete_nonexistent_no_error(self, index):
        """Deleting a session that doesn't exist does not raise."""
        index.delete_session("ghost")  # should not raise

    def test_close_does_not_raise(self, tmp_path):
        """close() completes without error."""
        idx = SessionIndex(db_path=tmp_path / "close_test.db")
        idx.close()  # should not raise

    def test_all_summary_fields_round_trip(self, index):
        """All SessionSummary fields survive upsert + get."""
        summary = SessionSummary(
            session_id="full",
            start_time="2026-04-06T10:00:00Z",
            end_time="2026-04-06T11:00:00Z",
            message_count=42,
            readiness_start=0.45,
            readiness_end=0.88,
            emotional_arc="improving",
        )
        index.upsert_session(summary)
        result = index.get_session("full")
        assert result.session_id == summary.session_id
        assert result.start_time == summary.start_time
        assert result.end_time == summary.end_time
        assert result.message_count == summary.message_count
        assert result.readiness_start == pytest.approx(0.45)
        assert result.readiness_end == pytest.approx(0.88)
        assert result.emotional_arc == "improving"

    def test_list_sessions_empty(self, index):
        """list_sessions returns empty list when index is empty."""
        assert index.list_sessions() == []


# ===========================================================================
# Integration tests
# ===========================================================================

class TestIntegration:
    """End-to-end scenarios combining writer, reader, and index."""

    def test_write_then_read_back(self, tmp_path):
        """Write events, then read them back via reader."""
        session_id = "sess_roundtrip"
        writer = SessionHistoryWriter(history_dir=tmp_path)
        reader = SessionHistoryReader(history_dir=tmp_path)

        events = _make_events(10, session_id=session_id)
        for ev in events:
            writer.append_event(ev)

        page = reader.fetch_latest(session_id)
        assert len(page.events) == 10
        assert [e.id for e in page.events] == [e.id for e in events]
        assert page.has_more is False

    def test_pagination_end_to_end(self, tmp_path):
        """Write 250 events, paginate through them 100 at a time."""
        session_id = "sess_paginate"
        writer = SessionHistoryWriter(history_dir=tmp_path)
        reader = SessionHistoryReader(history_dir=tmp_path)

        events = _make_events(250, session_id=session_id)
        for ev in events:
            writer.append_event(ev)

        # Page 1: last 100 events (150..249)
        page1 = reader.fetch_latest(session_id, limit=100)
        assert len(page1.events) == 100
        assert page1.has_more is True
        assert page1.events[-1].id == events[249].id
        assert page1.events[0].id == events[150].id

        # Page 2: events 50..149
        page2 = reader.fetch_older(session_id, before_id=page1.first_id, limit=100)
        assert len(page2.events) == 100
        assert page2.has_more is True
        assert page2.events[-1].id == events[149].id
        assert page2.events[0].id == events[50].id

        # Page 3: events 0..49
        page3 = reader.fetch_older(session_id, before_id=page2.first_id, limit=100)
        assert len(page3.events) == 50
        assert page3.has_more is False
        assert page3.events[0].id == events[0].id

        # Verify no events lost — all 250 accounted for
        all_ids = (
            [e.id for e in page3.events]
            + [e.id for e in page2.events]
            + [e.id for e in page1.events]
        )
        assert all_ids == [e.id for e in events]

    def test_session_index_with_history_writer(self, tmp_path):
        """SessionIndex and SessionHistoryWriter work together."""
        history_dir = tmp_path / "history"
        writer = SessionHistoryWriter(history_dir=history_dir)
        reader = SessionHistoryReader(history_dir=history_dir)
        index = SessionIndex(db_path=tmp_path / "index.db")

        try:
            session_id = "conv_20260406_183000"

            # Simulate a session: write events and track in index
            index.upsert_session(SessionSummary(
                session_id=session_id,
                start_time="2026-04-06T18:30:00Z",
                message_count=0,
            ))

            events = _make_events(15, session_id=session_id)
            for ev in events:
                writer.append_event(ev)

            # Update index with final stats
            index.upsert_session(SessionSummary(
                session_id=session_id,
                start_time="2026-04-06T18:30:00Z",
                end_time="2026-04-06T19:00:00Z",
                message_count=15,
                readiness_start=0.6,
                readiness_end=0.8,
                emotional_arc="improving",
            ))

            # Verify via index
            summary = index.get_session(session_id)
            assert summary is not None
            assert summary.message_count == 15
            assert summary.emotional_arc == "improving"

            # Verify via reader
            page = reader.fetch_latest(session_id)
            assert len(page.events) == 15

            # Cross-check: index lists this session
            listed = index.list_sessions()
            assert len(listed) == 1
            assert listed[0].session_id == session_id

            # Reader also lists this session
            assert session_id in reader.list_sessions()

        finally:
            index.close()

    def test_multiple_sessions_isolated(self, tmp_path):
        """Events from different sessions don't bleed into each other."""
        writer = SessionHistoryWriter(history_dir=tmp_path)
        reader = SessionHistoryReader(history_dir=tmp_path)

        events_a = _make_events(5, session_id="session_a")
        events_b = _make_events(8, session_id="session_b")

        for ev in events_a:
            writer.append_event(ev)
        for ev in events_b:
            writer.append_event(ev)

        page_a = reader.fetch_latest("session_a")
        page_b = reader.fetch_latest("session_b")

        assert len(page_a.events) == 5
        assert len(page_b.events) == 8
        assert all(e.session_id == "session_a" for e in page_a.events)
        assert all(e.session_id == "session_b" for e in page_b.events)

    def test_count_matches_written(self, tmp_path):
        """count_events matches the number of events written."""
        session_id = "sess_count"
        writer = SessionHistoryWriter(history_dir=tmp_path)
        reader = SessionHistoryReader(history_dir=tmp_path)

        events = _make_events(37, session_id=session_id)
        for ev in events:
            writer.append_event(ev)

        assert reader.count_events(session_id) == 37
