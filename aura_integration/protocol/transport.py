"""Aura transport protocol — abstract interface and stdio implementation.

Defines the contract all transports must implement and provides
:class:`StdioTransport`, a concrete transport that reads NDJSON from
stdin and writes to stdout.  This is the default transport used when
no sidecar process is running.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import AsyncIterator, Callable, Optional, Protocol, runtime_checkable

from src.aura.protocol.dedup import BoundedUUIDSet
from src.aura.protocol.messages import AuraMessage
from src.aura.protocol.ndjson import ndjson_parse_line, ndjson_safe_serialize

logger = logging.getLogger(__name__)


@runtime_checkable
class AuraTransport(Protocol):
    """Abstract transport protocol for Aura message I/O.

    All transports (stdio, WebSocket, IPC, etc.) must satisfy this
    structural interface.
    """

    def write(self, message: AuraMessage) -> None:
        """Write a single message to the transport.

        Args:
            message: The message to send.
        """
        ...

    def write_batch(self, messages: list[AuraMessage]) -> None:
        """Write multiple messages to the transport.

        Args:
            messages: List of messages to send.
        """
        ...

    def close(self) -> None:
        """Close the transport and release resources."""
        ...

    def is_connected(self) -> bool:
        """Return whether the transport is currently connected.

        Returns:
            ``True`` if the transport can accept writes.
        """
        ...


class StdioTransport:
    """Concrete transport that reads NDJSON from stdin and writes to stdout.

    This is the simplest transport, used by default when Aura runs as a
    standalone CLI without a sidecar or bridge process.

    Messages are deduplicated using a :class:`BoundedUUIDSet` so that
    echo loops are prevented when stdin and stdout are connected to the
    same pipe.

    Args:
        dedup_size: Maximum number of message IDs to track for
            deduplication. Defaults to ``1000``.
        on_message: Optional callback invoked for each parsed inbound
            message. If not set, use :meth:`read_messages` to iterate.
    """

    def __init__(
        self,
        *,
        dedup_size: int = 1000,
        on_message: Optional[Callable[[AuraMessage], None]] = None,
    ) -> None:
        self._connected = True
        self._dedup = BoundedUUIDSet(max_size=dedup_size)
        self._on_message = on_message

    # ── AuraTransport interface ──────────────────────────────────────

    def write(self, message: AuraMessage) -> None:
        """Write a single message as NDJSON to stdout.

        The message ID is recorded in the dedup set so that if the same
        message is read back from stdin it will be skipped.

        Args:
            message: The message to send.
        """
        if not self._connected:
            logger.warning("Attempted write on closed StdioTransport")
            return

        self._dedup.add(message.id)
        line = ndjson_safe_serialize(message.to_dict()) + "\n"
        try:
            sys.stdout.write(line)
            sys.stdout.flush()
        except (BrokenPipeError, OSError) as exc:
            logger.debug("Stdout write failed: %s", exc)
            self._connected = False

    def write_batch(self, messages: list[AuraMessage]) -> None:
        """Write multiple messages as consecutive NDJSON lines to stdout.

        Args:
            messages: List of messages to send.
        """
        for msg in messages:
            self.write(msg)

    def close(self) -> None:
        """Mark the transport as closed."""
        self._connected = False

    def is_connected(self) -> bool:
        """Return whether the transport is still open for writes."""
        return self._connected

    # ── Inbound (stdin) ──────────────────────────────────────────────

    def read_messages(self) -> AsyncIterator[AuraMessage]:
        """Async generator that yields parsed messages from stdin.

        Lines that fail to parse or whose IDs have already been seen
        (dedup) are silently skipped.

        Returns:
            An async iterator of :class:`AuraMessage` instances.
        """
        return self._read_stdin()

    async def _read_stdin(self) -> AsyncIterator[AuraMessage]:
        """Internal async generator reading lines from stdin."""
        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader()
        transport, _ = await loop.connect_read_pipe(
            lambda: asyncio.StreamReaderProtocol(reader),
            sys.stdin,
        )

        try:
            while self._connected:
                raw = await reader.readline()
                if not raw:
                    break  # EOF

                line = raw.decode("utf-8", errors="replace")
                parsed = ndjson_parse_line(line)
                if parsed is None:
                    continue

                msg = AuraMessage.from_dict(parsed)

                # Skip duplicates (echo prevention)
                if self._dedup.add(msg.id):
                    logger.debug("Skipping duplicate message id=%s", msg.id)
                    continue

                if self._on_message is not None:
                    self._on_message(msg)

                yield msg
        finally:
            transport.close()
