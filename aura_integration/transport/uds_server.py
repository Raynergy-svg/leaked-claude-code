"""Unix Domain Socket server — NDJSON bridge between Aura Python and the sidecar.

The UDS server:
1. Listens on a Unix socket for the Node.js sidecar to connect
2. Reads NDJSON messages from the sidecar (remote client → Aura)
3. Writes NDJSON messages to the sidecar (Aura → remote clients)

Uses only stdlib asyncio — no external dependencies.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Callable, Optional

from src.aura.protocol.messages import AuraMessage
from src.aura.protocol.ndjson import ndjson_safe_serialize, ndjson_parse_line
from src.aura.protocol.dedup import BoundedUUIDSet

logger = logging.getLogger(__name__)

DEFAULT_SOCKET_PATH = "/tmp/aura-sidecar.sock"


class UDSServer:
    """Async Unix domain socket server speaking NDJSON.

    Accepts a single client connection (the sidecar). If the sidecar
    reconnects, the old connection is replaced.

    Args:
        socket_path: Path to the Unix domain socket file.
        on_message: Callback invoked with each parsed AuraMessage from the sidecar.
        max_dedup: Maximum number of message IDs to track for deduplication.
    """

    def __init__(
        self,
        socket_path: str = DEFAULT_SOCKET_PATH,
        on_message: Optional[Callable[[AuraMessage], None]] = None,
        max_dedup: int = 1000,
    ):
        self.socket_path = socket_path
        self.on_message = on_message
        self._dedup = BoundedUUIDSet(max_size=max_dedup)
        self._server: Optional[asyncio.AbstractServer] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._connected = False
        self._running = False

    @property
    def connected(self) -> bool:
        """Whether the sidecar is currently connected."""
        return self._connected

    async def start(self) -> None:
        """Start the UDS server and begin accepting connections."""
        # Clean up stale socket file
        sock_path = Path(self.socket_path)
        if sock_path.exists():
            sock_path.unlink()

        # Ensure parent directory exists
        sock_path.parent.mkdir(parents=True, exist_ok=True)

        self._server = await asyncio.start_unix_server(
            self._handle_client,
            path=self.socket_path,
        )
        self._running = True
        logger.info(f"UDS server listening on {self.socket_path}")

    async def stop(self) -> None:
        """Stop the UDS server and clean up."""
        self._running = False
        if self._writer and not self._writer.is_closing():
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
        self._writer = None
        self._connected = False

        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        # Clean up socket file
        sock_path = Path(self.socket_path)
        if sock_path.exists():
            try:
                sock_path.unlink()
            except OSError:
                pass

        logger.info("UDS server stopped")

    async def write(self, msg: AuraMessage) -> bool:
        """Write a message to the sidecar.

        Returns True if the message was sent, False if not connected.
        """
        if not self._connected or not self._writer or self._writer.is_closing():
            return False

        try:
            line = ndjson_safe_serialize(msg.to_dict()) + "\n"
            self._writer.write(line.encode("utf-8"))
            await self._writer.drain()
            return True
        except (ConnectionError, OSError) as e:
            logger.warning(f"UDS write failed: {e}")
            self._connected = False
            return False

    def write_sync(self, msg: AuraMessage) -> bool:
        """Fire-and-forget write (schedules async write on the event loop).

        Use this from synchronous code. Returns True if connected
        (does not guarantee delivery).
        """
        if not self._connected or not self._writer:
            return False

        try:
            line = ndjson_safe_serialize(msg.to_dict()) + "\n"
            self._writer.write(line.encode("utf-8"))
            # Don't await drain — fire and forget
            return True
        except (ConnectionError, OSError):
            self._connected = False
            return False

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a sidecar connection."""
        # Replace any existing connection
        if self._writer and not self._writer.is_closing():
            logger.info("UDS: Replacing existing sidecar connection")
            self._writer.close()

        self._writer = writer
        self._connected = True
        logger.info("UDS: Sidecar connected")

        buffer = ""
        try:
            while self._running:
                data = await reader.read(65536)
                if not data:
                    break  # EOF — sidecar disconnected

                buffer += data.decode("utf-8")
                lines = buffer.split("\n")
                buffer = lines.pop()  # Keep incomplete last line

                for line in lines:
                    parsed = ndjson_parse_line(line)
                    if parsed is None:
                        continue

                    # Validate it looks like an AuraMessage
                    if not isinstance(parsed, dict) or "id" not in parsed:
                        continue

                    msg_id = parsed.get("id", "")
                    if self._dedup.add(msg_id):
                        continue  # Duplicate

                    try:
                        msg = AuraMessage.from_dict(parsed)
                        if self.on_message:
                            self.on_message(msg)
                    except Exception as e:
                        logger.warning(f"UDS: Failed to parse message: {e}")

        except (ConnectionError, asyncio.CancelledError):
            pass
        except Exception as e:
            logger.error(f"UDS: Unexpected error: {e}")
        finally:
            self._connected = False
            if not writer.is_closing():
                writer.close()
            logger.info("UDS: Sidecar disconnected")
