"""Aura transport layer — sidecar lifecycle management and UDS server.

Phase 2 of the real-time transport integration.  Provides:
    UDSServer       Async Unix domain socket server (NDJSON protocol)
    SidecarManager  Manages the Node.js sidecar subprocess lifecycle
    RemoteTransport AuraTransport implementation over UDS ↔ sidecar
"""

from src.aura.transport.uds_server import UDSServer
from src.aura.transport.sidecar import SidecarManager
from src.aura.transport.remote import RemoteTransport

__all__ = [
    "UDSServer",
    "SidecarManager",
    "RemoteTransport",
]
