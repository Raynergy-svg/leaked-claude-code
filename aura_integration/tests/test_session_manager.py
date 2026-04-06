"""Tests for RemoteSessionManager (Phase 5).

Validates client-to-companion routing, LRU eviction, session lifecycle,
and message handling without spinning up real AuraCompanion instances.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch, call

from src.aura.protocol.messages import AuraMessage, MessageType, create_message
from src.aura.transport.session_manager import RemoteSessionManager


# ── Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def mock_companion_class(monkeypatch):
    """Replace AuraCompanion with a lightweight mock to avoid heavy init."""
    mock_cls = MagicMock()
    mock_instance = MagicMock()
    mock_instance.process_input.return_value = "mocked response"
    mock_instance.end_session.return_value = None
    # Each call to the class constructor returns a fresh mock, but we keep
    # a reference to the *first* one for simple single-client tests.
    instances = []

    def _make_instance(*args, **kwargs):
        inst = MagicMock()
        inst.process_input.return_value = "mocked response"
        inst.end_session.return_value = None
        instances.append(inst)
        return inst

    mock_cls.side_effect = _make_instance
    monkeypatch.setattr(
        "src.aura.transport.session_manager.AuraCompanion", mock_cls
    )
    return mock_cls, instances


@pytest.fixture
def manager(tmp_path, mock_companion_class):
    """Create a RemoteSessionManager with temp dirs and mocked companion."""
    db_dir = tmp_path / "db"
    bridge_dir = tmp_path / "bridge"
    db_dir.mkdir()
    bridge_dir.mkdir()
    return RemoteSessionManager(
        db_dir=db_dir,
        bridge_dir=bridge_dir,
        max_sessions=3,
    )


def _user_msg(text: str, client_id: str | None = None) -> AuraMessage:
    """Helper to build a user_message with optional client_id."""
    data: dict = {"text": text}
    if client_id is not None:
        data["client_id"] = client_id
    return create_message(MessageType.USER_MESSAGE, data)


def _disconnect_msg(client_id: str) -> AuraMessage:
    """Helper to build a control_request / disconnect message."""
    return create_message(
        MessageType.CONTROL_REQUEST,
        {"subtype": "disconnect", "client_id": client_id},
    )


# ── TestRemoteSessionManager ────────────────────────────────────────────

class TestRemoteSessionManager:
    """Core tests for session routing, lifecycle, and eviction."""

    # 1 ─ init empty
    def test_init_empty(self, manager):
        """Fresh manager has zero sessions."""
        assert manager.session_count() == 0
        assert manager.active_sessions() == []

    # 2 ─ first message creates session
    def test_handle_user_message_creates_session(
        self, manager, mock_companion_class
    ):
        mock_cls, instances = mock_companion_class
        msg = _user_msg("hello", client_id="client-1")

        response = manager.handle_message(msg)

        # A companion was instantiated
        assert mock_cls.call_count == 1
        assert manager.session_count() == 1
        # The companion's process_input was called with the text
        instances[0].process_input.assert_called_once_with("hello")
        # We got a response back
        assert response is not None
        assert response.type == MessageType.AURA_RESPONSE.value

    # 3 ─ same client_id reuses session
    def test_handle_user_message_reuses_session(
        self, manager, mock_companion_class
    ):
        mock_cls, instances = mock_companion_class
        msg1 = _user_msg("first", client_id="client-1")
        msg2 = _user_msg("second", client_id="client-1")

        manager.handle_message(msg1)
        manager.handle_message(msg2)

        # Only one companion created
        assert mock_cls.call_count == 1
        assert manager.session_count() == 1
        # But process_input was called twice on the same instance
        assert instances[0].process_input.call_count == 2
        instances[0].process_input.assert_any_call("first")
        instances[0].process_input.assert_any_call("second")

    # 4 ─ different clients get separate companions
    def test_multiple_clients_get_separate_sessions(
        self, manager, mock_companion_class
    ):
        mock_cls, instances = mock_companion_class
        manager.handle_message(_user_msg("hi", client_id="alice"))
        manager.handle_message(_user_msg("yo", client_id="bob"))

        assert mock_cls.call_count == 2
        assert manager.session_count() == 2
        instances[0].process_input.assert_called_once_with("hi")
        instances[1].process_input.assert_called_once_with("yo")

    # 5 ─ LRU eviction when max_sessions reached
    def test_max_sessions_evicts_oldest(self, manager, mock_companion_class):
        mock_cls, instances = mock_companion_class

        # Fill to max (3)
        manager.handle_message(_user_msg("a", client_id="c1"))
        manager.handle_message(_user_msg("b", client_id="c2"))
        manager.handle_message(_user_msg("c", client_id="c3"))
        assert manager.session_count() == 3

        # Adding a 4th should evict the least-recently-used (c1)
        manager.handle_message(_user_msg("d", client_id="c4"))
        assert manager.session_count() == 3
        assert "c1" not in manager.active_sessions()
        assert "c4" in manager.active_sessions()
        # Evicted companion's end_session should have been called
        instances[0].end_session.assert_called_once()

    # 6 ─ disconnect removes session
    def test_disconnect_removes_session(self, manager, mock_companion_class):
        mock_cls, instances = mock_companion_class
        manager.handle_message(_user_msg("hi", client_id="client-1"))
        assert manager.session_count() == 1

        response = manager.handle_message(_disconnect_msg("client-1"))

        assert manager.session_count() == 0
        assert "client-1" not in manager.active_sessions()
        instances[0].end_session.assert_called_once()

    # 7 ─ response includes client_id
    def test_response_includes_client_id(self, manager, mock_companion_class):
        msg = _user_msg("hello", client_id="client-42")
        response = manager.handle_message(msg)

        assert response is not None
        assert response.data.get("client_id") == "client-42"

    # 8 ─ shutdown ends all sessions
    def test_shutdown_ends_all_sessions(self, manager, mock_companion_class):
        mock_cls, instances = mock_companion_class
        manager.handle_message(_user_msg("a", client_id="c1"))
        manager.handle_message(_user_msg("b", client_id="c2"))
        assert manager.session_count() == 2

        manager.shutdown()

        assert manager.session_count() == 0
        for inst in instances:
            inst.end_session.assert_called_once()

    # 9 ─ active_sessions returns list of ids
    def test_active_sessions_returns_ids(self, manager, mock_companion_class):
        manager.handle_message(_user_msg("a", client_id="alpha"))
        manager.handle_message(_user_msg("b", client_id="beta"))

        ids = manager.active_sessions()
        assert set(ids) == {"alpha", "beta"}

    # 10 ─ session_count
    def test_session_count(self, manager, mock_companion_class):
        assert manager.session_count() == 0
        manager.handle_message(_user_msg("a", client_id="c1"))
        assert manager.session_count() == 1
        manager.handle_message(_user_msg("b", client_id="c2"))
        assert manager.session_count() == 2
        manager.handle_message(_disconnect_msg("c1"))
        assert manager.session_count() == 1

    # 11 ─ unknown message type doesn't crash
    def test_handle_unknown_message_type(self, manager, mock_companion_class):
        mock_cls, _ = mock_companion_class
        msg = create_message(MessageType.STREAM_EVENT, {"payload": "stuff"})

        # Should not raise, should not create a session
        result = manager.handle_message(msg)
        assert manager.session_count() == 0
        assert mock_cls.call_count == 0

    # 12 ─ missing client_id falls back to "default"
    def test_default_client_id(self, manager, mock_companion_class):
        mock_cls, instances = mock_companion_class
        msg = _user_msg("hello")  # no client_id in data

        response = manager.handle_message(msg)

        assert manager.session_count() == 1
        assert "default" in manager.active_sessions()
        instances[0].process_input.assert_called_once_with("hello")
        assert response.data.get("client_id") == "default"


# ── Edge-case extras ────────────────────────────────────────────────────

class TestRemoteSessionManagerEdgeCases:
    """Additional edge-case coverage."""

    def test_eviction_updates_lru_on_reuse(self, tmp_path, mock_companion_class):
        """Re-accessing an existing session refreshes its LRU position."""
        mock_cls, instances = mock_companion_class
        db_dir = tmp_path / "db"
        bridge_dir = tmp_path / "bridge"
        db_dir.mkdir()
        bridge_dir.mkdir()
        mgr = RemoteSessionManager(
            db_dir=db_dir, bridge_dir=bridge_dir, max_sessions=3
        )

        mgr.handle_message(_user_msg("a", client_id="c1"))
        mgr.handle_message(_user_msg("b", client_id="c2"))
        mgr.handle_message(_user_msg("c", client_id="c3"))

        # Touch c1 to make it recently used
        mgr.handle_message(_user_msg("refresh", client_id="c1"))

        # Now add c4 — c2 (the true LRU) should be evicted, not c1
        mgr.handle_message(_user_msg("d", client_id="c4"))
        assert "c1" in mgr.active_sessions()
        assert "c2" not in mgr.active_sessions()
        assert "c4" in mgr.active_sessions()

    def test_disconnect_nonexistent_client_is_noop(
        self, manager, mock_companion_class
    ):
        """Disconnecting a client_id that doesn't exist should not raise."""
        result = manager.handle_message(_disconnect_msg("ghost"))
        assert manager.session_count() == 0

    def test_shutdown_is_idempotent(self, manager, mock_companion_class):
        """Calling shutdown twice should not raise."""
        manager.handle_message(_user_msg("x", client_id="c1"))
        manager.shutdown()
        manager.shutdown()  # second call — no crash
        assert manager.session_count() == 0
