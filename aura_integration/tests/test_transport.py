"""Tests for the Aura transport layer (Phase 2).

Tests the UDS server, sidecar manager, and remote transport.
Integration test verifies NDJSON message flow over Unix domain sockets.
"""

import asyncio
import json
import os
import tempfile
import time
import threading
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.aura.protocol.messages import AuraMessage, MessageType, create_message
from src.aura.protocol.ndjson import ndjson_safe_serialize
from src.aura.transport.uds_server import UDSServer
from src.aura.transport.sidecar import SidecarManager


# ── UDS Server ────────────────────────────────────────────────────────────

class TestUDSServer:
    def test_init_defaults(self):
        server = UDSServer()
        assert server.socket_path == "/tmp/aura-sidecar.sock"
        assert not server.connected

    def test_init_custom_path(self):
        server = UDSServer(socket_path="/tmp/test-aura.sock")
        assert server.socket_path == "/tmp/test-aura.sock"

    def test_not_connected_initially(self):
        server = UDSServer()
        assert not server.connected

    def test_write_fails_when_not_connected(self):
        server = UDSServer()
        msg = create_message(MessageType.AURA_RESPONSE, {"text": "hello"})
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(server.write(msg))
        loop.close()
        assert result is False

    def test_write_sync_fails_when_not_connected(self):
        server = UDSServer()
        msg = create_message(MessageType.AURA_RESPONSE, {"text": "hello"})
        assert server.write_sync(msg) is False


class TestUDSServerAsync:
    """Integration test: actual UDS connection between two asyncio endpoints."""

    @pytest.fixture
    def socket_path(self, tmp_path):
        return str(tmp_path / "test.sock")

    def test_uds_message_roundtrip(self, socket_path):
        """Verify messages flow through UDS server correctly."""
        received = []

        def on_message(msg):
            received.append(msg)

        loop = asyncio.new_event_loop()

        async def run_test():
            # Start server
            server = UDSServer(
                socket_path=socket_path,
                on_message=on_message,
            )
            await server.start()

            # Connect a client
            reader, writer = await asyncio.open_unix_connection(socket_path)

            # Send a message from "client" (simulating sidecar)
            msg = create_message(MessageType.USER_MESSAGE, {"text": "test input"})
            line = ndjson_safe_serialize(msg.to_dict()) + "\n"
            writer.write(line.encode("utf-8"))
            await writer.drain()

            # Give time for processing
            await asyncio.sleep(0.1)

            # Verify received
            assert len(received) == 1
            assert received[0].type == MessageType.USER_MESSAGE
            assert received[0].data["text"] == "test input"

            # Test server writing back
            response = create_message(MessageType.AURA_RESPONSE, {"text": "hi"})
            success = await server.write(response)
            assert success is True

            # Read the response on the client side
            data = await asyncio.wait_for(reader.readline(), timeout=1.0)
            parsed = json.loads(data.decode("utf-8"))
            assert parsed["type"] == "aura_response"
            assert parsed["data"]["text"] == "hi"

            # Cleanup
            writer.close()
            await writer.wait_closed()
            await server.stop()

        loop.run_until_complete(run_test())
        loop.close()

    def test_uds_dedup(self, socket_path):
        """Verify duplicate messages are filtered by UUID."""
        received = []

        def on_message(msg):
            received.append(msg)

        loop = asyncio.new_event_loop()

        async def run_test():
            server = UDSServer(
                socket_path=socket_path,
                on_message=on_message,
            )
            await server.start()

            reader, writer = await asyncio.open_unix_connection(socket_path)

            # Send the same message twice
            msg = create_message(MessageType.USER_MESSAGE, {"text": "dup test"})
            line = ndjson_safe_serialize(msg.to_dict()) + "\n"
            writer.write(line.encode("utf-8"))
            writer.write(line.encode("utf-8"))  # Same ID = duplicate
            await writer.drain()

            await asyncio.sleep(0.1)

            # Should only receive once
            assert len(received) == 1

            writer.close()
            await writer.wait_closed()
            await server.stop()

        loop.run_until_complete(run_test())
        loop.close()

    def test_uds_invalid_json_ignored(self, socket_path):
        """Invalid NDJSON lines should be silently ignored."""
        received = []

        def on_message(msg):
            received.append(msg)

        loop = asyncio.new_event_loop()

        async def run_test():
            server = UDSServer(
                socket_path=socket_path,
                on_message=on_message,
            )
            await server.start()

            reader, writer = await asyncio.open_unix_connection(socket_path)

            # Send garbage, then a valid message
            writer.write(b"not json\n")
            writer.write(b"{}\n")  # Missing 'id' field

            msg = create_message(MessageType.USER_MESSAGE, {"text": "valid"})
            line = ndjson_safe_serialize(msg.to_dict()) + "\n"
            writer.write(line.encode("utf-8"))
            await writer.drain()

            await asyncio.sleep(0.1)

            # Only the valid message should arrive
            assert len(received) == 1
            assert received[0].data["text"] == "valid"

            writer.close()
            await writer.wait_closed()
            await server.stop()

        loop.run_until_complete(run_test())
        loop.close()

    def test_uds_client_reconnect(self, socket_path):
        """Server should accept a new client after the first disconnects."""
        received = []

        def on_message(msg):
            received.append(msg)

        loop = asyncio.new_event_loop()

        async def run_test():
            server = UDSServer(
                socket_path=socket_path,
                on_message=on_message,
            )
            await server.start()

            # First client
            _, writer1 = await asyncio.open_unix_connection(socket_path)
            msg1 = create_message(MessageType.USER_MESSAGE, {"text": "first"})
            writer1.write((ndjson_safe_serialize(msg1.to_dict()) + "\n").encode())
            await writer1.drain()
            await asyncio.sleep(0.05)
            writer1.close()
            await writer1.wait_closed()
            await asyncio.sleep(0.1)

            # Second client (reconnection)
            _, writer2 = await asyncio.open_unix_connection(socket_path)
            msg2 = create_message(MessageType.USER_MESSAGE, {"text": "second"})
            writer2.write((ndjson_safe_serialize(msg2.to_dict()) + "\n").encode())
            await writer2.drain()
            await asyncio.sleep(0.05)

            assert len(received) == 2
            assert received[0].data["text"] == "first"
            assert received[1].data["text"] == "second"

            writer2.close()
            await writer2.wait_closed()
            await server.stop()

        loop.run_until_complete(run_test())
        loop.close()

    def test_uds_socket_cleanup(self, socket_path):
        """Socket file should be cleaned up after stop."""
        loop = asyncio.new_event_loop()

        async def run_test():
            server = UDSServer(socket_path=socket_path)
            await server.start()
            assert Path(socket_path).exists()
            await server.stop()
            assert not Path(socket_path).exists()

        loop.run_until_complete(run_test())
        loop.close()


# ── Sidecar Manager ───────────────────────────────────────────────────────

class TestSidecarManager:
    def test_init_defaults(self):
        mgr = SidecarManager()
        assert not mgr.running
        assert mgr.pid is None

    def test_status_when_not_running(self):
        mgr = SidecarManager()
        status = mgr.status()
        assert status["running"] is False
        assert status["pid"] is None
        assert "socket_path" in status
        assert "ws_port" in status

    def test_stop_when_not_running(self):
        """stop() should not raise when the sidecar isn't running."""
        mgr = SidecarManager()
        mgr.stop()  # Should be a no-op

    def test_start_without_node(self):
        """start() should return False gracefully when Node.js is not found."""
        mgr = SidecarManager()
        with patch.object(mgr, '_find_node', return_value=None):
            result = mgr.start()
            assert result is False

    def test_custom_config(self):
        mgr = SidecarManager(
            ws_port=9999,
            ws_host="127.0.0.1",
            auth_token="secret123",
        )
        assert mgr.ws_port == 9999
        assert mgr.ws_host == "127.0.0.1"
        assert mgr.auth_token == "secret123"
