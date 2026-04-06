"""Aura structured message protocol — NDJSON transport layer.

Phase 1 of the real-time transport integration.  Provides typed,
deduplicated message I/O over NDJSON streams.

Public API:
    Message types:  AuraMessage, MessageType, create_message
    Serialization:  ndjson_safe_serialize, ndjson_parse_line
    Async I/O:      NdjsonReader, NdjsonWriter
    Deduplication:  BoundedUUIDSet
    Transport:      AuraTransport, StdioTransport
"""

from src.aura.protocol.dedup import BoundedUUIDSet
from src.aura.protocol.messages import AuraMessage, MessageType, create_message
from src.aura.protocol.ndjson import (
    NdjsonReader,
    NdjsonWriter,
    ndjson_parse_line,
    ndjson_safe_serialize,
)
from src.aura.protocol.transport import AuraTransport, StdioTransport

__all__ = [
    "AuraMessage",
    "AuraTransport",
    "BoundedUUIDSet",
    "MessageType",
    "NdjsonReader",
    "NdjsonWriter",
    "StdioTransport",
    "create_message",
    "ndjson_parse_line",
    "ndjson_safe_serialize",
]
