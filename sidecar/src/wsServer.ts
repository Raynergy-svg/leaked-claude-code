/**
 * WebSocket server — accepts remote client connections.
 */

import { WebSocketServer, WebSocket } from "ws";
import type { IncomingMessage } from "node:http";
import { randomUUID } from "node:crypto";
import { ndjsonSerialize, ndjsonParse } from "./ndjson.js";
import type { AuraMessage, SidecarConfig } from "./types.js";

const KEEP_ALIVE_INTERVAL_MS = 300_000;
const PING_INTERVAL_MS = 10_000;
const MAX_SEEN_IDS = 1000;

type ClientState = {
  ws: WebSocket;
  id: string;
  alive: boolean;
  seenIds: Set<string>;
};

export type WSServerOptions = {
  host: string;
  port: number;
  authToken?: string;
  onClientMessage: (msg: AuraMessage, clientId: string) => void;
  onClientConnect?: (clientId: string) => void;
  onClientDisconnect?: (clientId: string) => void;
};

export class WSServer {
  private wss: WebSocketServer | null = null;
  private clients = new Map<string, ClientState>();
  private pingInterval: NodeJS.Timeout | null = null;
  private keepAliveInterval: NodeJS.Timeout | null = null;
  private readonly options: WSServerOptions & {
    onClientConnect: (clientId: string) => void;
    onClientDisconnect: (clientId: string) => void;
  };

  constructor(options: WSServerOptions) {
    this.options = {
      onClientConnect: () => {},
      onClientDisconnect: () => {},
      ...options,
    };
  }

  start(): void {
    this.wss = new WebSocketServer({
      host: this.options.host,
      port: this.options.port,
      verifyClient: this.options.authToken
        ? (info, callback) => {
            const url = new URL(info.req.url ?? "/", `http://${info.req.headers.host}`);
            const token = url.searchParams.get("token") ?? info.req.headers.authorization?.replace("Bearer ", "");
            if (token === this.options.authToken) { callback(true); } else { callback(false, 403, "Unauthorized"); }
          }
        : undefined,
    });

    this.wss.on("connection", (ws: WebSocket, req: IncomingMessage) => {
      const clientId = randomUUID();
      const state: ClientState = { ws, id: clientId, alive: true, seenIds: new Set() };
      this.clients.set(clientId, state);
      console.log(`[WS] Client connected: ${clientId} from ${req.socket.remoteAddress}`);
      this.options.onClientConnect!(clientId);

      ws.on("pong", () => { state.alive = true; });
      ws.on("message", (data: Buffer) => {
        const raw = data.toString("utf-8");
        const lines = raw.split("\n").filter((l) => l.trim());
        for (const line of lines) {
          const parsed = ndjsonParse(line);
          if (parsed && typeof parsed === "object" && "id" in parsed && "type" in parsed) {
            const msg = parsed as AuraMessage;
            if (state.seenIds.has(msg.id)) continue;
            state.seenIds.add(msg.id);
            if (state.seenIds.size > MAX_SEEN_IDS) {
              const first = state.seenIds.values().next().value;
              if (first) state.seenIds.delete(first);
            }
            this.options.onClientMessage(msg, clientId);
          }
        }
      });
      ws.on("close", () => { this.clients.delete(clientId); console.log(`[WS] Client disconnected: ${clientId}`); this.options.onClientDisconnect!(clientId); });
      ws.on("error", (err: Error) => { console.error(`[WS] Client ${clientId} error: ${err.message}`); });
    });

    this.wss.on("listening", () => { console.log(`[WS] Server listening on ${this.options.host}:${this.options.port}`); });
    this.wss.on("error", (err: Error) => { console.error(`[WS] Server error: ${err.message}`); });

    this.pingInterval = setInterval(() => {
      for (const [clientId, state] of this.clients) {
        if (!state.alive) { console.log(`[WS] Client ${clientId} failed ping, terminating`); state.ws.terminate(); this.clients.delete(clientId); this.options.onClientDisconnect!(clientId); continue; }
        state.alive = false; state.ws.ping();
      }
    }, PING_INTERVAL_MS);

    this.keepAliveInterval = setInterval(() => {
      const frame = ndjsonSerialize({ type: "keep_alive" });
      for (const state of this.clients.values()) { if (state.ws.readyState === WebSocket.OPEN) { state.ws.send(frame + "\n"); } }
    }, KEEP_ALIVE_INTERVAL_MS);
  }

  broadcast(msg: AuraMessage): void {
    const line = ndjsonSerialize(msg) + "\n";
    for (const state of this.clients.values()) {
      if (state.ws.readyState === WebSocket.OPEN) {
        if (!state.seenIds.has(msg.id)) { state.seenIds.add(msg.id); if (state.seenIds.size > MAX_SEEN_IDS) { const first = state.seenIds.values().next().value; if (first) state.seenIds.delete(first); } state.ws.send(line); }
      }
    }
  }

  sendTo(clientId: string, msg: AuraMessage): void {
    const state = this.clients.get(clientId);
    if (state && state.ws.readyState === WebSocket.OPEN) { state.ws.send(ndjsonSerialize(msg) + "\n"); }
  }

  get clientCount(): number { return this.clients.size; }

  close(): void {
    if (this.pingInterval) { clearInterval(this.pingInterval); this.pingInterval = null; }
    if (this.keepAliveInterval) { clearInterval(this.keepAliveInterval); this.keepAliveInterval = null; }
    for (const state of this.clients.values()) { state.ws.close(1000, "Server shutting down"); }
    this.clients.clear();
    if (this.wss) { this.wss.close(); this.wss = null; }
  }
}
