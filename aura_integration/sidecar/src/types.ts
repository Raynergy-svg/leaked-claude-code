/**
 * Shared types for the Aura sidecar transport layer.
 *
 * These mirror the Python protocol.messages module so both sides
 * speak the same message format.
 */

export type MessageType =
  | "user_message"
  | "aura_response"
  | "control_request"
  | "control_response"
  | "stream_event"
  | "readiness_update"
  | "override_event"
  | "bridge_status";

export type AuraMessage = {
  id: string;
  type: MessageType;
  timestamp: string;
  data: Record<string, unknown>;
};

export type TransportState =
  | "idle"
  | "connected"
  | "reconnecting"
  | "closing"
  | "closed";

export type SidecarConfig = {
  /** Unix domain socket path for Python ↔ sidecar communication. */
  udsPath: string;
  /** WebSocket URL for remote clients to connect to. */
  wsHost: string;
  wsPort: number;
  /** Optional auth token for remote client connections. */
  authToken?: string;
  /** Max reconnect time budget (ms). Default 600000 (10 min). */
  reconnectGiveUpMs?: number;
  /** Ping interval for health checks (ms). Default 10000. */
  pingIntervalMs?: number;
  /** Keep-alive interval (ms). Default 300000 (5 min). */
  keepAliveIntervalMs?: number;
  /** Max buffered messages for replay. Default 1000. */
  maxBufferSize?: number;
};

export const DEFAULT_CONFIG: Required<SidecarConfig> = {
  udsPath: "/tmp/aura-sidecar.sock",
  wsHost: "0.0.0.0",
  wsPort: 8765,
  authToken: "",
  reconnectGiveUpMs: 600_000,
  pingIntervalMs: 10_000,
  keepAliveIntervalMs: 300_000,
  maxBufferSize: 1000,
};
