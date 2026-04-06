#!/usr/bin/env node
/**
 * Aura Sidecar Bridge — connects Aura's Python process to remote clients.
 *
 * Architecture:
 *   [Remote Client] <--WebSocket--> [This Sidecar] <--NDJSON/UDS--> [Aura Python]
 *
 * The sidecar:
 * 1. Connects to Aura Python via a Unix domain socket (NDJSON protocol)
 * 2. Accepts WebSocket connections from remote clients (IDEs, web UIs)
 * 3. Forwards messages bidirectionally with UUID-based deduplication
 *
 * Usage:
 *   node dist/auraBridge.js [--uds-path PATH] [--ws-port PORT] [--auth-token TOKEN]
 *
 * Environment variables:
 *   AURA_UDS_PATH     Unix socket path (default: /tmp/aura-sidecar.sock)
 *   AURA_WS_PORT      WebSocket port (default: 8765)
 *   AURA_WS_HOST      WebSocket host (default: 0.0.0.0)
 *   AURA_AUTH_TOKEN    Optional auth token for WebSocket clients
 */

import { UDSClient } from "./udsClient.js";
import { WSServer } from "./wsServer.js";
import type { AuraMessage } from "./types.js";
import { DEFAULT_CONFIG } from "./types.js";

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

function parseArgs(): {
  udsPath: string;
  wsHost: string;
  wsPort: number;
  authToken: string;
} {
  const args = process.argv.slice(2);
  const config = {
    udsPath: process.env.AURA_UDS_PATH ?? DEFAULT_CONFIG.udsPath,
    wsHost: process.env.AURA_WS_HOST ?? DEFAULT_CONFIG.wsHost,
    wsPort: parseInt(process.env.AURA_WS_PORT ?? "", 10) || DEFAULT_CONFIG.wsPort,
    authToken: process.env.AURA_AUTH_TOKEN ?? DEFAULT_CONFIG.authToken,
  };

  for (let i = 0; i < args.length; i++) {
    switch (args[i]) {
      case "--uds-path":
        config.udsPath = args[++i] ?? config.udsPath;
        break;
      case "--ws-port":
        config.wsPort = parseInt(args[++i] ?? "", 10) || config.wsPort;
        break;
      case "--ws-host":
        config.wsHost = args[++i] ?? config.wsHost;
        break;
      case "--auth-token":
        config.authToken = args[++i] ?? config.authToken;
        break;
    }
  }

  return config;
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

function main(): void {
  const config = parseArgs();

  console.log("[Aura Sidecar] Starting...");
  console.log(`  UDS path:  ${config.udsPath}`);
  console.log(`  WS server: ${config.wsHost}:${config.wsPort}`);
  console.log(`  Auth:      ${config.authToken ? "enabled" : "disabled"}`);

  // Track connection state for status reporting
  let pythonConnected = false;

  // --- UDS Client (sidecar ↔ Python) ---
  const uds = new UDSClient({
    socketPath: config.udsPath,
    onMessage: (msg: AuraMessage) => {
      // Forward Python → remote clients
      wsServer.broadcast(msg);
    },
    onConnect: () => {
      pythonConnected = true;
      console.log("[Bridge] Python process connected");
    },
    onDisconnect: () => {
      pythonConnected = false;
      console.log("[Bridge] Python process disconnected");
    },
  });

  // --- WebSocket Server (remote clients ↔ sidecar) ---
  const wsServer = new WSServer({
    host: config.wsHost,
    port: config.wsPort,
    authToken: config.authToken || undefined,
    onClientMessage: (msg: AuraMessage, clientId: string) => {
      // Forward remote client → Python
      if (!uds.isConnected()) {
        console.log(
          `[Bridge] Dropping message from ${clientId}: Python not connected`
        );
        return;
      }
      uds.write(msg);
    },
    onClientConnect: (clientId: string) => {
      console.log(
        `[Bridge] Remote client ${clientId} connected (total: ${wsServer.clientCount})`
      );
    },
    onClientDisconnect: (clientId: string) => {
      console.log(
        `[Bridge] Remote client ${clientId} disconnected (total: ${wsServer.clientCount})`
      );
    },
  });

  // Start both
  wsServer.start();
  uds.connect();

  // --- Graceful shutdown ---
  const shutdown = (signal: string) => {
    console.log(`\n[Aura Sidecar] Received ${signal}, shutting down...`);
    wsServer.close();
    uds.close();
    process.exit(0);
  };

  process.on("SIGINT", () => shutdown("SIGINT"));
  process.on("SIGTERM", () => shutdown("SIGTERM"));

  // --- Health status on SIGUSR1 ---
  process.on("SIGUSR1", () => {
    console.log("[Aura Sidecar] Status:");
    console.log(`  Python connected: ${pythonConnected}`);
    console.log(`  Remote clients:   ${wsServer.clientCount}`);
  });
}

main();
