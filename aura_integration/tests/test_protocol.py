"""Tests for the NDJSON structured message protocol module."""

import json
import pytest

from src.aura.protocol.messages import AuraMessage, MessageType, create_message
from src.aura.protocol.ndjson import ndjson_safe_serialize, ndjson_parse_line
from src.aura.protocol.dedup import BoundedUUIDSet


# ── NDJSON Serialization ──────────────────────────────────────────────────

class TestNdjsonSafeSerialize:
    def test_basic_dict(self):
        result = ndjson_safe_serialize({"key": "value"})
        assert json.loads(result) == {"key": "value"}
        assert "\n" not in result

    def test_escapes_u2028(self):
        """U+2028 LINE SEPARATOR must be escaped to \\u2028."""
        result = ndjson_safe_serialize({"text": "hello\u2028world"})
        assert "\u2028" not in result
        assert "\\u2028" in result
        # Must still parse back to the original value
        assert json.loads(result) == {"text": "hello\u2028world"}

    def test_escapes_u2029(self):
        """U+2029 PARAGRAPH SEPARATOR must be escaped to \\u2029."""
        result = ndjson_safe_serialize({"text": "hello\u2029world"})
        assert "\u2029" not in result
        assert "\\u2029" in result
        assert json.loads(result) == {"text": "hello\u2029world"}

    def test_no_trailing_newline(self):
        result = ndjson_safe_serialize({"a": 1})
        assert not result.endswith("\n")

    def test_none_value(self):
        result = ndjson_safe_serialize(None)
        assert result == "null"


class TestNdjsonParseLine:
    def test_valid_json(self):
        result = ndjson_parse_line('{"key": "value"}')
        assert result == {"key": "value"}

    def test_invalid_json_returns_none(self):
        assert ndjson_parse_line("not json") is None

    def test_empty_string_returns_none(self):
        assert ndjson_parse_line("") is None

    def test_strips_whitespace(self):
        result = ndjson_parse_line('  {"a": 1}  ')
        assert result == {"a": 1}


# ── Message Types ─────────────────────────────────────────────────────────

class TestAuraMessage:
    def test_create_message(self):
        msg = create_message(MessageType.USER_MESSAGE, {"text": "hello"})
        assert msg.type == MessageType.USER_MESSAGE
        assert msg.data == {"text": "hello"}
        assert len(msg.id) == 36  # UUID format
        assert "T" in msg.timestamp  # ISO 8601

    def test_roundtrip(self):
        msg = create_message(MessageType.READINESS_UPDATE, {"score": 85})
        d = msg.to_dict()
        restored = AuraMessage.from_dict(d)
        assert restored.id == msg.id
        assert restored.type == msg.type
        assert restored.data == msg.data
        assert restored.timestamp == msg.timestamp

    def test_all_message_types_exist(self):
        expected = {
            "user_message", "aura_response", "control_request",
            "control_response", "stream_event", "readiness_update",
            "override_event", "bridge_status",
        }
        actual = {mt.value for mt in MessageType}
        assert actual == expected

    def test_serializes_to_ndjson(self):
        msg = create_message(MessageType.BRIDGE_STATUS, {"connected": True})
        line = ndjson_safe_serialize(msg.to_dict())
        parsed = json.loads(line)
        assert parsed["type"] == "bridge_status"
        assert parsed["data"]["connected"] is True


# ── Bounded UUID Set ──────────────────────────────────────────────────────

class TestBoundedUUIDSet:
    def test_new_id_not_seen(self):
        s = BoundedUUIDSet(max_size=10)
        assert not s.add("abc")  # first time → not a dup

    def test_duplicate_detected(self):
        s = BoundedUUIDSet(max_size=10)
        s.add("abc")
        assert s.add("abc")  # second time → duplicate

    def test_contains(self):
        s = BoundedUUIDSet(max_size=10)
        s.add("abc")
        assert "abc" in s
        assert "xyz" not in s

    def test_eviction_at_capacity(self):
        s = BoundedUUIDSet(max_size=3)
        s.add("a")
        s.add("b")
        s.add("c")
        s.add("d")  # evicts "a"
        assert "a" not in s
        assert "b" in s
        assert "d" in s

    def test_duplicate_refreshes_position(self):
        s = BoundedUUIDSet(max_size=3)
        s.add("a")
        s.add("b")
        s.add("c")
        s.add("a")  # refresh "a" — now "b" is oldest
        s.add("d")  # should evict "b", not "a"
        assert "a" in s
        assert "b" not in s

    def test_len(self):
        s = BoundedUUIDSet(max_size=5)
        s.add("a")
        s.add("b")
        s.add("a")  # dup
        assert len(s) == 2
