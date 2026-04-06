"""Sidecar lifecycle manager — spawns and monitors the Node.js transport sidecar.

The sidecar is OPTIONAL. Aura works as a standalone CLI when the sidecar
is not running. This manager handles:
1. Starting the Node.js sidecar subprocess
2. Monitoring its health (restart on crash)
3. Graceful shutdown

Usage:
    manager = SidecarManager(sidecar_dir="/path/to/sidecar")
    manager.start()      # spawns the Node process
    ...
    manager.stop()       # graceful shutdown
"""

from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Default sidecar directory relative to project root
DEFAULT_SIDECAR_DIR = Path(__file__).resolve().parent.parent.parent.parent / "sidecar"


class SidecarManager:
    """Manages the Node.js sidecar subprocess lifecycle.

    Args:
        sidecar_dir: Path to the sidecar/ directory containing package.json.
        socket_path: Unix socket path for UDS communication.
        ws_port: WebSocket port for remote clients.
        ws_host: WebSocket host to bind to.
        auth_token: Optional auth token for WebSocket client connections.
        auto_restart: Whether to restart the sidecar on crash. Default True.
        max_restarts: Maximum number of restarts before giving up. Default 5.
        restart_cooldown: Seconds between restarts. Default 5.
    """

    def __init__(
        self,
        sidecar_dir: Optional[Path] = None,
        socket_path: str = "/tmp/aura-sidecar.sock",
        ws_port: int = 8765,
        ws_host: str = "0.0.0.0",
        auth_token: Optional[str] = None,
        auto_restart: bool = True,
        max_restarts: int = 5,
        restart_cooldown: float = 5.0,
    ):
        self.sidecar_dir = sidecar_dir or DEFAULT_SIDECAR_DIR
        self.socket_path = socket_path
        self.ws_port = ws_port
        self.ws_host = ws_host
        self.auth_token = auth_token
        self.auto_restart = auto_restart
        self.max_restarts = max_restarts
        self.restart_cooldown = restart_cooldown

        self._process: Optional[subprocess.Popen] = None
        self._monitor_thread: Optional[threading.Thread] = None
        self._stopping = False
        self._restart_count = 0
        self._last_restart_time = 0.0

    @property
    def running(self) -> bool:
        """Whether the sidecar process is currently running."""
        return self._process is not None and self._process.poll() is None

    @property
    def pid(self) -> Optional[int]:
        """PID of the sidecar process, or None if not running."""
        return self._process.pid if self._process and self._process.poll() is None else None

    def _find_node(self) -> Optional[str]:
        """Find the Node.js binary."""
        return shutil.which("node")

    def _check_sidecar_built(self) -> bool:
        """Check if the sidecar has been built (dist/ exists)."""
        return (self.sidecar_dir / "dist" / "auraBridge.js").exists()

    def _build_sidecar(self) -> bool:
        """Build the sidecar if not already built."""
        if self._check_sidecar_built():
            return True

        node = self._find_node()
        if not node:
            logger.error("Node.js not found — cannot build sidecar")
            return False

        logger.info("Building sidecar...")
        try:
            # Install deps if needed
            if not (self.sidecar_dir / "node_modules").exists():
                subprocess.run(
                    ["npm", "install"],
                    cwd=str(self.sidecar_dir),
                    check=True,
                    capture_output=True,
                    timeout=60,
                )

            # Build
            subprocess.run(
                ["npx", "tsc"],
                cwd=str(self.sidecar_dir),
                check=True,
                capture_output=True,
                timeout=30,
            )
            logger.info("Sidecar built successfully")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Sidecar build failed: {e.stderr.decode()}")
            return False
        except subprocess.TimeoutExpired:
            logger.error("Sidecar build timed out")
            return False

    def start(self) -> bool:
        """Start the sidecar subprocess.

        Returns True if the sidecar was started, False on failure.
        """
        if self.running:
            logger.info("Sidecar already running")
            return True

        node = self._find_node()
        if not node:
            logger.warning(
                "Node.js not found — sidecar disabled. "
                "Aura will run in local CLI mode only."
            )
            return False

        if not self._build_sidecar():
            return False

        self._stopping = False
        return self._spawn()

    def _spawn(self) -> bool:
        """Spawn the sidecar Node process."""
        node = self._find_node()
        if not node:
            return False

        entry = str(self.sidecar_dir / "dist" / "auraBridge.js")

        env = os.environ.copy()
        env["AURA_UDS_PATH"] = self.socket_path
        env["AURA_WS_PORT"] = str(self.ws_port)
        env["AURA_WS_HOST"] = self.ws_host
        if self.auth_token:
            env["AURA_AUTH_TOKEN"] = self.auth_token

        try:
            self._process = subprocess.Popen(
                [node, entry],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                # Don't inherit stdin — sidecar doesn't need it
                stdin=subprocess.DEVNULL,
            )
            logger.info(f"Sidecar started (PID {self._process.pid})")

            # Start monitor thread
            self._monitor_thread = threading.Thread(
                target=self._monitor_loop,
                daemon=True,
                name="aura-sidecar-monitor",
            )
            self._monitor_thread.start()

            return True
        except OSError as e:
            logger.error(f"Failed to start sidecar: {e}")
            return False

    def _monitor_loop(self) -> None:
        """Monitor the sidecar process and handle restarts."""
        proc = self._process
        if proc is None:
            return

        # Read and log stdout/stderr
        if proc.stdout:
            for line in iter(proc.stdout.readline, b""):
                if self._stopping:
                    break
                text = line.decode("utf-8", errors="replace").rstrip()
                if text:
                    logger.info(f"[sidecar] {text}")

        # Process exited
        returncode = proc.wait()
        if self._stopping:
            return

        logger.warning(f"Sidecar exited with code {returncode}")

        # Auto-restart logic
        if not self.auto_restart:
            return

        now = time.monotonic()
        # Reset restart count if enough time has passed
        if now - self._last_restart_time > 60:
            self._restart_count = 0

        if self._restart_count >= self.max_restarts:
            logger.error(
                f"Sidecar crashed {self._restart_count} times in 60s — "
                "giving up. Aura continues in local CLI mode."
            )
            return

        self._restart_count += 1
        self._last_restart_time = now

        logger.info(
            f"Restarting sidecar in {self.restart_cooldown}s "
            f"(attempt {self._restart_count}/{self.max_restarts})"
        )
        time.sleep(self.restart_cooldown)

        if not self._stopping:
            self._spawn()

    def stop(self) -> None:
        """Gracefully stop the sidecar."""
        self._stopping = True

        if self._process and self._process.poll() is None:
            logger.info(f"Stopping sidecar (PID {self._process.pid})")
            try:
                self._process.send_signal(signal.SIGTERM)
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning("Sidecar didn't stop gracefully, killing")
                self._process.kill()
                self._process.wait(timeout=2)
            except OSError:
                pass

        self._process = None

        # Clean up socket file
        sock = Path(self.socket_path)
        if sock.exists():
            try:
                sock.unlink()
            except OSError:
                pass

    def status(self) -> dict:
        """Return sidecar status for diagnostics."""
        return {
            "running": self.running,
            "pid": self.pid,
            "restart_count": self._restart_count,
            "socket_path": self.socket_path,
            "ws_port": self.ws_port,
            "ws_host": self.ws_host,
            "sidecar_dir": str(self.sidecar_dir),
            "sidecar_built": self._check_sidecar_built(),
        }
