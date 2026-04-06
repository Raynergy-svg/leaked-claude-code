"""RemoteSessionManager — maps remote client connections to isolated AuraCompanion instances.

Each WebSocket client gets its own AuraCompanion with separate:
- ConversationProcessor
- ReadinessComputer
- Self-model graph (in-memory per session)
- Session history

Architecture:
    [WS Client A] -> sidecar -> UDS -> SessionManager -> CompanionA
    [WS Client B] -> sidecar -> UDS -> SessionManager -> CompanionB

Used by the ``--serve`` CLI flag for headless multi-session server mode.
"""

from __future__ import annotations

import logging
import signal
import threading
from pathlib import Path
from typing import Optional

from src.aura.protocol.messages import AuraMessage, MessageType, create_message
from src.aura.transport.remote import RemoteTransport
from src.aura.cli.companion import AuraCompanion

logger = logging.getLogger(__name__)


class RemoteSessionManager:
    """Maps remote client connections to isolated AuraCompanion instances.

    Each WebSocket client gets its own AuraCompanion with separate:
    - ConversationProcessor
    - ReadinessComputer
    - Self-model graph (in-memory per session)
    - Session history

    Args:
        db_dir: Directory for per-client database files.
        bridge_dir: Path to bridge signal directory.
        max_sessions: Maximum concurrent sessions before evicting the oldest.
    """

    def __init__(
        self,
        db_dir: Path,
        bridge_dir: Path,
        max_sessions: int = 10,
    ):
        self._sessions: dict[str, object] = {}  # client_id -> AuraCompanion
        self._session_order: list[str] = []  # insertion order for eviction
        self._db_dir = db_dir
        self._bridge_dir = bridge_dir
        self._max_sessions = max_sessions
        self._transport: Optional[RemoteTransport] = None
        self._lock = threading.Lock()

    def set_transport(self, transport: RemoteTransport) -> None:
        """Set the transport used to send responses back to clients.

        Args:
            transport: The RemoteTransport instance for outbound messages.
        """
        self._transport = transport

    def handle_message(self, msg: AuraMessage) -> Optional[AuraMessage]:
        """Route incoming message to the correct companion session.

        Dispatches based on ``client_id`` in ``msg.data``:
        - USER_MESSAGE: route to the companion for that client (creating one
          if needed). Returns the response message.
        - CONTROL_REQUEST with subtype ``disconnect``: tear down that client's session.

        Args:
            msg: The inbound message from the sidecar.

        Returns:
            The response AuraMessage for USER_MESSAGE, or None otherwise.
        """
        client_id = msg.data.get("client_id", "default")

        if msg.type == MessageType.USER_MESSAGE:
            text = msg.data.get("text", "")
            if not text:
                logger.debug("Ignoring empty USER_MESSAGE from client %s", client_id)
                return None

            companion = self._get_or_create_session(client_id)
            try:
                response = companion.process_input(text)  # type: ignore[union-attr]
            except Exception:
                logger.exception("Error processing input for client %s", client_id)
                response = "I'm sorry, something went wrong processing your message."

            # Send response back tagged with client_id
            resp_msg = create_message(
                MessageType.AURA_RESPONSE,
                {
                    "text": response,
                    "client_id": client_id,
                },
            )
            if self._transport:
                self._transport.write(resp_msg)
            return resp_msg

        elif msg.type == MessageType.CONTROL_REQUEST:
            subtype = msg.data.get("subtype")
            if subtype == "disconnect":
                logger.info("Client %s requested disconnect", client_id)
                self._remove_session(client_id)

        return None

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def _get_or_create_session(self, client_id: str) -> object:
        """Return the AuraCompanion for *client_id*, creating one if needed.

        If the session limit is reached, the oldest session is evicted.

        Args:
            client_id: Unique identifier for the remote client.

        Returns:
            The AuraCompanion instance bound to *client_id*.
        """
        with self._lock:
            if client_id in self._sessions:
                # Refresh LRU position
                if client_id in self._session_order:
                    self._session_order.remove(client_id)
                    self._session_order.append(client_id)
                return self._sessions[client_id]

            if len(self._sessions) >= self._max_sessions:
                # Evict oldest session
                oldest = self._session_order[0]
                logger.info(
                    "Session limit reached (%d). Evicting oldest session: %s",
                    self._max_sessions,
                    oldest,
                )
                self._remove_session_unlocked(oldest)

            companion = self._create_companion(client_id)
            try:
                companion.start_session()  # type: ignore[union-attr]
            except Exception:
                logger.exception("Failed to start session for client %s", client_id)

            self._sessions[client_id] = companion
            self._session_order.append(client_id)
            logger.info(
                "Created session for client %s (active: %d)",
                client_id,
                len(self._sessions),
            )
            return companion

    def _create_companion(self, client_id: str) -> object:
        """Create an isolated AuraCompanion for *client_id*.

        Each companion gets its own database file under ``self._db_dir``.

        Args:
            client_id: Unique identifier for the remote client.

        Returns:
            A new AuraCompanion instance.
        """
        self._db_dir.mkdir(parents=True, exist_ok=True)
        db_path = self._db_dir / f"{client_id}.db"
        return AuraCompanion(db_path=db_path, bridge_dir=self._bridge_dir)

    def _remove_session(self, client_id: str) -> None:
        """Thread-safe removal of a session.

        Args:
            client_id: The client whose session should be torn down.
        """
        with self._lock:
            self._remove_session_unlocked(client_id)

    def _remove_session_unlocked(self, client_id: str) -> None:
        """Remove a session without acquiring the lock (caller must hold it).

        Args:
            client_id: The client whose session should be torn down.
        """
        if client_id not in self._sessions:
            return

        try:
            self._sessions[client_id].end_session()  # type: ignore[union-attr]
        except Exception:
            logger.exception("Error ending session for client %s", client_id)

        del self._sessions[client_id]
        if client_id in self._session_order:
            self._session_order.remove(client_id)

        logger.info(
            "Removed session for client %s (active: %d)",
            client_id,
            len(self._sessions),
        )

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def active_sessions(self) -> list[str]:
        """Return a list of active client IDs."""
        with self._lock:
            return list(self._sessions.keys())

    def session_count(self) -> int:
        """Return the number of active sessions."""
        with self._lock:
            return len(self._sessions)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        """Gracefully tear down all sessions."""
        with self._lock:
            client_ids = list(self._sessions.keys())

        for cid in client_ids:
            self._remove_session(cid)

        logger.info("Session manager shut down — all sessions closed")

    def serve(
        self,
        socket_path: str = "/tmp/aura-sidecar.sock",
        ws_port: int = 8765,
        auth_token: Optional[str] = None,
    ) -> None:
        """Start the transport and block until a termination signal is received.

        This is the main entry point for ``--serve`` mode. It:
        1. Creates a RemoteTransport with this manager's handle_message callback
        2. Starts the UDS server and sidecar
        3. Blocks on a threading.Event until SIGINT or SIGTERM
        4. Calls shutdown() on exit

        Args:
            socket_path: Unix socket path for UDS communication.
            ws_port: WebSocket port for remote clients.
            auth_token: Optional auth token for WebSocket connections.
        """
        stop_event = threading.Event()

        def _signal_handler(signum: int, frame: object) -> None:
            logger.info("Received signal %d, initiating shutdown...", signum)
            stop_event.set()

        transport = RemoteTransport(
            socket_path=socket_path,
            on_message=self.handle_message,
        )
        transport._sidecar.ws_port = ws_port
        if auth_token:
            transport._sidecar.auth_token = auth_token

        self._transport = transport

        if not transport.start():
            logger.error("Failed to start remote transport — aborting serve")
            return

        logger.info(
            "Aura multi-session server running (UDS: %s, WS port: %d)",
            socket_path,
            ws_port,
        )

        # Install signal handlers (must be done from the main thread)
        prev_sigint = signal.signal(signal.SIGINT, _signal_handler)
        prev_sigterm = signal.signal(signal.SIGTERM, _signal_handler)

        try:
            stop_event.wait()
        finally:
            signal.signal(signal.SIGINT, prev_sigint)
            signal.signal(signal.SIGTERM, prev_sigterm)
            logger.info("Shutting down multi-session server...")
            self.shutdown()
            transport.close()
            logger.info("Multi-session server stopped")
