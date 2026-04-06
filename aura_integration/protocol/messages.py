"""Aura structured message types.

Defines the typed, discriminated message protocol used for all Aura
transport communication.  Each message carries a UUID, ISO-8601 timestamp,
type discriminator, and an arbitrary data payload.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict


class MessageType(str, Enum):
    """Discriminator values for the Aura message protocol."""

    USER_MESSAGE = "user_message"
    AURA_RESPONSE = "aura_response"
    CONTROL_REQUEST = "control_request"
    CONTROL_RESPONSE = "control_response"
    STREAM_EVENT = "stream_event"
    READINESS_UPDATE = "readiness_update"
    OVERRIDE_EVENT = "override_event"
    BRIDGE_STATUS = "bridge_status"


@dataclass
class AuraMessage:
    """A single structured message in the Aura protocol.

    Attributes:
        id: Unique message identifier (UUID4).
        type: Discriminator string from :class:`MessageType`.
        timestamp: ISO-8601 UTC timestamp of message creation.
        data: Arbitrary payload dict.
    """

    id: str
    type: str
    timestamp: str
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize this message to a plain dict suitable for JSON encoding."""
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> AuraMessage:
        """Deserialize a dict into an :class:`AuraMessage`.

        Missing keys fall back to sensible defaults so that partially
        formed messages from external sources can still be ingested.

        Args:
            raw: Dict with ``id``, ``type``, ``timestamp``, and ``data`` keys.

        Returns:
            An AuraMessage instance.
        """
        return cls(
            id=raw.get("id", str(uuid.uuid4())),
            type=raw.get("type", ""),
            timestamp=raw.get("timestamp", _utc_now_iso()),
            data=raw.get("data", {}),
        )


def create_message(
    msg_type: MessageType | str,
    data: Dict[str, Any] | None = None,
) -> AuraMessage:
    """Factory that creates an :class:`AuraMessage` with auto-filled id and timestamp.

    Args:
        msg_type: The message type discriminator.  Accepts a
            :class:`MessageType` enum member or a raw string.
        data: Optional payload dict.  Defaults to an empty dict.

    Returns:
        A new AuraMessage ready for transport.
    """
    type_value = msg_type.value if isinstance(msg_type, MessageType) else msg_type
    return AuraMessage(
        id=str(uuid.uuid4()),
        type=type_value,
        timestamp=_utc_now_iso(),
        data=data or {},
    )


def _utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()
