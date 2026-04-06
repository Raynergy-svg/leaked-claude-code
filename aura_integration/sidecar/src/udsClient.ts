/**
 * Unix Domain Socket client — connects the sidecar to the Aura Python process.
 *
 * Speaks NDJSON over the socket. Each line is one AuraMessage.
 * Auto-reconnects if the Python process restarts.
 */

import * as net from "node:net";
import { ndjsonSerialize, ndjsonParse } from "./ndjson.js";
import type { AuraMessage } from "./types.js";

export type UDSClientOptions = {
  socketPath: string;
  /** Called when a complete NDJSON message arrives from Python. */
  onMessage: (msg: AuraMessage) => void;
  /** Called when the connection state changes. */
  onConnect?: () => void;
  onDisconnect?: () => void;
  /** Reconnect delay (ms). Default 2000. */
  reconnectDelayMs?: number;
};

export class UDSClient {
  private socket: net.Socket | null = null;
  private buffer = "";
  private connected = false;
  private closing = false;
  private reconnectTimer: NodeJS.Timeout | null = null;
  private readonly options: Required<UDSClientOptions>;

  constructor(options: UDSClientOptions) {
    this.options = {
      reconnectDelayMs: 2000,
      onConnect: () => {},
      onDisconnect: () => {},
      ...options,
    };
  }

  connect(): void {
    if (this.closing) return;

    this.socket = net.createConnection(this.options.socketPath);

    this.socket.on("connect", () => {
      this.connected = true;
      this.buffer = "";
      console.log(`[UDS] Connected to ${this.options.socketPath}`);
      this.options.onConnect!();
    });

    this.socket.on("data", (chunk: Buffer) => {
      this.buffer += chunk.toString("utf-8");
      this.processBuffer();
    });

    this.socket.on("close", () => {
      const wasConnected = this.connected;
      this.connected = false;
      this.socket = null;
      if (wasConnected) {
        console.log("[UDS] Disconnected from Python process");
        this.options.onDisconnect!();
      }
      if (!this.closing) {
        this.scheduleReconnect();
      }
    });

    this.socket.on("error", (err: Error) => {
      // ENOENT = socket file doesn't exist yet (Python not started)
      // ECONNREFUSED = Python process not listening yet
      if (
        (err as NodeJS.ErrnoException).code !== "ENOENT" &&
        (err as NodeJS.ErrnoException).code !== "ECONNREFUSED"
      ) {
        console.error(`[UDS] Error: ${err.message}`);
      }
      // close event will fire next and handle reconnection
    });
  }

  write(msg: AuraMessage): boolean {
    if (!this.connected || !this.socket) return false;
    try {
      this.socket.write(ndjsonSerialize(msg) + "\n");
      return true;
    } catch {
      return false;
    }
  }

  isConnected(): boolean {
    return this.connected;
  }

  close(): void {
    this.closing = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.socket) {
      this.socket.destroy();
      this.socket = null;
    }
    this.connected = false;
  }

  private processBuffer(): void {
    const lines = this.buffer.split("\n");
    // Keep the last (possibly incomplete) line in the buffer
    this.buffer = lines.pop() ?? "";

    for (const line of lines) {
      const parsed = ndjsonParse(line);
      if (parsed && typeof parsed === "object" && "id" in parsed) {
        this.options.onMessage(parsed as AuraMessage);
      }
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer) return;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      if (!this.closing) {
        this.connect();
      }
    }, this.options.reconnectDelayMs);
  }
}
