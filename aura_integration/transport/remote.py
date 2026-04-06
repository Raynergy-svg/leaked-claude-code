"""RemoteTransport — AuraTransport implementation over UDS to the sidecar.

This is the transport that AuraCompanion uses when running in --remote mode.
It replaces StdioTransport's stdin/stdout with a UDS connection to the
Node.js sidecar, which in turn connects to remote WebSocket clients.

Architecture:
    [AuraCompanion] → RemoteTransport → UDSServer → [Sidecar] → [WS Clients]
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Callable, Optional

from src.aura.protocol.messages import AuraMessage, MessageType, create_message
from src.aura.transport.uds_server import UDSServer
from src.aura.transport.sidecar import SidecarManager

logger = logging.getLogger(__name__)


class RemoteTransport:
    """Transport that routes messages through the sidecar to remote clients.

    Manages both the UDS server (for sidecar communication) and the
    sidecar subprocess lifecycle. Can be used as an AuraTransport.

    Args:
        socket_path: Unix socket path for UDS communication.
        sidecar_manager: Optional pre-configured SidecarManager.
        on_message: Callback for messages received from remote clients.
    """

    def __init__(
        self,
        socket_path: str = "/tmp/aura-sidecar.sock",
        sidecar_manager: Optional[SidecarManager] = None,
        on_message: Optional[Callable[[AuraMessage], None]] = None,
    ):
        self.on_message = on_message
        self._socket_path = socket_path
        self._uds = UDSServer(
            socket_path=socket_path,
            on_message=self._handle_message,
        )
        self._sidecar = sidecar_manager or SidecarManager(
            socket_path=socket_path,
        )
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._connected = False

    def _handle_message(self, msg: AuraMessage) -> None:
        """Handle a message from the sidecar (i.e., from a remote client)."""
        if self.on_message:
            self.on_message(msg)

    def start(self) -> bool:
        """Start the remote transport (UDS server + sidecar).

        Returns True if both started successfully.
        """
        # Start the sidecar first
        if not self._sidecar.start():
            logger.warning("Sidecar failed to start — remote transport unavailable")
            return False

        # Start the async event loop for UDS in a background thread
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name="aura-remote-transport",
        )
        self._thread.start()

        # Wait briefly for UDS server to be ready
        import time
        for _ in range(10):
            if self._connected:
                break
            time.sleep(0.1)

        logger.info("Remote transport started")
        return True

    def _run_loop(self) -> None:
        """Run the asyncio event loop for UDS server."""
        assert self._loop is not None
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._uds.start())
            self._connected = True
            self._loop.run_forever()
        except Exception as e:
            logger.error(f"Remote transport loop error: {e}")
        finally:
            self._connected = False

    def write(self, msg: AuraMessage) -> None:
        """Write a message to remote clients via the sidecar."""
        if self._loop and not self._loop.is_closed():
            asyncio.run_coroutine_threadsafe(
                self._uds.write(msg),
                self._loop,
            )

    def write_batch(self, messages: list[AuraMessage]) -> None:
        """Write multiple messages to remote clients."""
        for msg in messages:
            self.write(msg)

    def is_connected(self) -> bool:
        """Whether the sidecar is connected via UDS."""
        return self._uds.connected

    def close(self) -> None:
        """Stop the remote transport."""
        # Stop the UDS server
        if self._loop and not self._loop.is_closed():
            asyncio.run_coroutine_threadsafe(
                self._uds.stop(),
                self._loop,
            ).result(timeout=5)
            self._loop.call_soon_threadsafe(self._loop.stop)

        if self._thread:
            self._thread.join(timeout=5)

        if self._loop and not self._loop.is_closed():
            self._loop.close()

        # Stop the sidecar
        self._sidecar.stop()

        self._connected = False
        logger.info("Remote transport stopped")

    def status(self) -> dict:
        """Return transport status for diagnostics."""
        return {
            "transport": "remote",
            "uds_connected": self._uds.connected,
            "sidecar": self._sidecar.status(),
        }
