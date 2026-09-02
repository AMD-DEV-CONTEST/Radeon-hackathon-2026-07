"use client";

import { io, type Socket } from "socket.io-client";

import { env } from "@/config/env";
import { useAuthStore } from "@/features/auth/store/auth.store";
import { refreshAccessToken } from "@/services/api/axios";
import {
  SOCKET_EVENTS,
  type AgentStatusUpdatedPayload,
  type SocketNotificationPayload,
  type SocketPayloadMap,
} from "@/services/websocket/events";
import { useSocketStore } from "@/services/websocket/socket.store";

type SocketListener<T> = (payload: T) => void;

const HEARTBEAT_INTERVAL_MS = 15_000;
const PONG_TIMEOUT_MS = 10_000;

const FORWARDED_EVENTS = [
  SOCKET_EVENTS.interviewStarted,
  SOCKET_EVENTS.interviewEnded,
  SOCKET_EVENTS.questionChanged,
  SOCKET_EVENTS.transcriptUpdated,
  SOCKET_EVENTS.aiThinking,
  SOCKET_EVENTS.aiResponse,
  SOCKET_EVENTS.candidateSpeaking,
  SOCKET_EVENTS.evaluationUpdated,
  SOCKET_EVENTS.progressUpdated,
] as const;

function nowIso(): string {
  return new Date().toISOString();
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value === "object" && value !== null) {
    return value as Record<string, unknown>;
  }
  return null;
}

function getErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message) {
    return error.message;
  }
  if (typeof error === "string" && error.length > 0) {
    return error;
  }
  const record = asRecord(error);
  if (record && typeof record.message === "string") {
    return record.message;
  }
  return "WebSocket connection failed.";
}

/**
 * Production singleton Socket.IO client with JWT auth, heartbeat,
 * reconnect strategy, and typed event registration.
 */
class SocketManager {
  private static instance: SocketManager | null = null;

  private socket: Socket | null = null;
  private intentionalDisconnect = false;
  private consumerCount = 0;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private pongTimer: ReturnType<typeof setTimeout> | null = null;
  private lastPingAt = 0;
  private authRefreshPromise: Promise<string | null> | null = null;
  private unsubscribeAuth: (() => void) | null = null;
  private readonly localListeners = new Map<
    string,
    Set<SocketListener<unknown>>
  >();

  static getInstance(): SocketManager {
    SocketManager.instance ??= new SocketManager();
    return SocketManager.instance;
  }

  getSocket(): Socket | null {
    return this.socket;
  }

  isConnected(): boolean {
    return Boolean(this.socket?.connected);
  }

  connect(): void {
    if (typeof window === "undefined") {
      return;
    }

    this.consumerCount += 1;
    this.intentionalDisconnect = false;
    this.ensureSocket();
  }

  /** Force-close regardless of active consumers (logout / hard reset). */
  disconnect(): void {
    this.consumerCount = 0;
    this.teardown("client_disconnect");
  }

  release(): void {
    this.consumerCount = Math.max(0, this.consumerCount - 1);
    if (this.consumerCount === 0) {
      this.teardown("client_release");
    }
  }

  private ensureSocket(): void {
    if (this.socket?.connected) {
      useSocketStore.getState().setStatus("connected");
      return;
    }

    if (this.socket && !this.socket.connected) {
      useSocketStore.getState().setStatus("connecting");
      this.socket.auth = { token: this.getAccessToken() };
      this.socket.connect();
      return;
    }

    useSocketStore.getState().setStatus("connecting");

    this.socket = io(env.wsUrl, {
      autoConnect: false,
      transports: ["websocket"],
      withCredentials: true,
      auth: {
        token: this.getAccessToken(),
      },
      reconnection: true,
      reconnectionAttempts: Infinity,
      reconnectionDelay: 1_000,
      reconnectionDelayMax: 15_000,
      randomizationFactor: 0.5,
      timeout: 20_000,
    });

    this.bindSocketLifecycle(this.socket);
    this.bindAuthSubscription();
    this.socket.connect();
  }

  private teardown(reason: string): void {
    this.intentionalDisconnect = true;
    this.stopHeartbeat();
    this.clearPongTimer();

    if (this.socket) {
      this.socket.removeAllListeners();
      this.socket.disconnect();
      this.socket = null;
    }

    this.unsubscribeAuth?.();
    this.unsubscribeAuth = null;

    useSocketStore.getState().setStatus("disconnected");
    useSocketStore.getState().setReconnectAttempt(0);
    this.emitLocal(SOCKET_EVENTS.disconnect, {
      at: nowIso(),
      reason,
    });
  }

  on<E extends keyof SocketPayloadMap>(
    event: E,
    listener: SocketListener<SocketPayloadMap[E]>
  ): () => void {
    const key = String(event);
    const bucket =
      this.localListeners.get(key) ?? new Set<SocketListener<unknown>>();
    bucket.add(listener as SocketListener<unknown>);
    this.localListeners.set(key, bucket);

    return () => {
      bucket.delete(listener as SocketListener<unknown>);
      if (bucket.size === 0) {
        this.localListeners.delete(key);
      }
    };
  }

  off<E extends keyof SocketPayloadMap>(
    event: E,
    listener?: SocketListener<SocketPayloadMap[E]>
  ): void {
    const key = String(event);
    const bucket = this.localListeners.get(key);
    if (!bucket) {
      return;
    }

    if (listener) {
      bucket.delete(listener as SocketListener<unknown>);
      if (bucket.size === 0) {
        this.localListeners.delete(key);
      }
      return;
    }

    bucket.clear();
    this.localListeners.delete(key);
  }

  emit<E extends keyof SocketPayloadMap>(
    event: E,
    payload: SocketPayloadMap[E]
  ): void {
    if (!this.socket?.connected) {
      this.connect();
    }
    this.socket?.emit(String(event), payload);
  }

  async reauthenticate(): Promise<boolean> {
    const token = await this.ensureFreshToken();
    if (!token || !this.socket) {
      useSocketStore.getState().setStatus("auth_failed");
      this.emitLocal(SOCKET_EVENTS.authError, {
        at: nowIso(),
        message: "Authentication failed.",
      });
      return false;
    }

    this.socket.auth = { token };
    this.socket.emit(SOCKET_EVENTS.authenticate, { token });
    return true;
  }

  private getAccessToken(): string | null {
    return useAuthStore.getState().accessToken;
  }

  private async ensureFreshToken(): Promise<string | null> {
    const current = this.getAccessToken();
    if (current) {
      return current;
    }

    this.authRefreshPromise ??= refreshAccessToken().finally(() => {
      this.authRefreshPromise = null;
    });

    return this.authRefreshPromise;
  }

  private bindAuthSubscription(): void {
    this.unsubscribeAuth?.();
    let previousToken = this.getAccessToken();

    this.unsubscribeAuth = useAuthStore.subscribe((state) => {
      const nextToken = state.accessToken;
      if (nextToken === previousToken) {
        return;
      }

      previousToken = nextToken;

      if (!nextToken) {
        this.disconnect();
        return;
      }

      if (!this.socket) {
        return;
      }

      this.socket.auth = { token: nextToken };

      if (this.socket.connected) {
        this.socket.emit(SOCKET_EVENTS.authenticate, { token: nextToken });
        return;
      }

      if (!this.intentionalDisconnect) {
        this.connect();
      }
    });
  }

  private bindSocketLifecycle(socket: Socket): void {
    socket.on("connect", () => {
      useSocketStore.getState().setStatus("connected");
      useSocketStore.getState().setReconnectAttempt(0);
      useSocketStore.getState().setLastError(null);
      this.emitLocal(SOCKET_EVENTS.connect, { at: nowIso() });
      void this.reauthenticate();
      this.startHeartbeat();
    });

    socket.on("disconnect", (reason) => {
      this.stopHeartbeat();
      this.clearPongTimer();

      if (this.intentionalDisconnect) {
        useSocketStore.getState().setStatus("disconnected");
      } else {
        useSocketStore.getState().setStatus("reconnecting");
      }

      this.emitLocal(SOCKET_EVENTS.disconnect, {
        at: nowIso(),
        reason: String(reason),
      });
    });

    socket.io.on("reconnect_attempt", (attempt) => {
      useSocketStore.getState().setStatus("reconnecting");
      useSocketStore.getState().setReconnectAttempt(attempt);
      socket.auth = { token: this.getAccessToken() };
      this.emitLocal(SOCKET_EVENTS.reconnectAttempt, {
        at: nowIso(),
        attempt,
      });
    });

    socket.io.on("reconnect", (attempt) => {
      useSocketStore.getState().setStatus("connected");
      useSocketStore.getState().setReconnectAttempt(0);
      this.emitLocal(SOCKET_EVENTS.reconnect, {
        at: nowIso(),
        attempt,
      });
      void this.reauthenticate();
    });

    socket.on("connect_error", (error) => {
      const message = getErrorMessage(error);
      useSocketStore.getState().setLastError(message);
      useSocketStore.getState().setStatus(
        message.toLowerCase().includes("auth") ? "auth_failed" : "error"
      );
      this.emitLocal(SOCKET_EVENTS.connectError, {
        at: nowIso(),
        message,
      });

      if (
        message.toLowerCase().includes("unauthorized") ||
        message.toLowerCase().includes("jwt") ||
        message.toLowerCase().includes("token")
      ) {
        void this.handleAuthFailure();
      }
    });

    socket.on(SOCKET_EVENTS.authenticated, () => {
      useSocketStore.getState().setStatus("connected");
      useSocketStore.getState().setLastError(null);
      this.emitLocal(SOCKET_EVENTS.authenticated, { at: nowIso() });
    });

    socket.on(SOCKET_EVENTS.authError, (payload: unknown) => {
      const record = asRecord(payload);
      const message =
        typeof record?.message === "string"
          ? record.message
          : "Authentication failed.";
      useSocketStore.getState().setStatus("auth_failed");
      useSocketStore.getState().setLastError(message);
      this.emitLocal(SOCKET_EVENTS.authError, {
        at: nowIso(),
        message,
      });
      void this.handleAuthFailure();
    });

    socket.on(SOCKET_EVENTS.pong, (payload: unknown) => {
      this.clearPongTimer();
      const record = asRecord(payload);
      const serverLatency =
        typeof record?.latencyMs === "number"
          ? record.latencyMs
          : typeof record?.latency_ms === "number"
            ? record.latency_ms
            : null;
      const latencyMs =
        serverLatency ??
        (this.lastPingAt > 0 ? Date.now() - this.lastPingAt : 0);

      useSocketStore.getState().setLatency(latencyMs);
      this.emitLocal(SOCKET_EVENTS.pong, {
        at: nowIso(),
        latencyMs,
      });
    });

    socket.on(SOCKET_EVENTS.heartbeat, () => {
      this.emitLocal(SOCKET_EVENTS.heartbeat, { at: nowIso() });
    });

    socket.on(SOCKET_EVENTS.notification, (payload: unknown) => {
      const record = asRecord(payload);
      if (!record) {
        return;
      }
      const level: SocketNotificationPayload["level"] =
        record.level === "warning" ||
        record.level === "error" ||
        record.level === "success" ||
        record.level === "info"
          ? record.level
          : "info";

      const notification: SocketNotificationPayload = {
        id: String(record.id ?? `notification-${Date.now()}`),
        title: String(record.title ?? "Notification"),
        message: String(record.message ?? ""),
        level,
        at: String(record.at ?? nowIso()),
      };
      useSocketStore.getState().setNotification(notification);
      this.emitLocal(SOCKET_EVENTS.notification, notification);
    });

    socket.on(SOCKET_EVENTS.systemError, (payload: unknown) => {
      const record = asRecord(payload);
      const error = {
        code: typeof record?.code === "string" ? record.code : null,
        message:
          typeof record?.message === "string"
            ? record.message
            : "A system error occurred.",
        retryable: Boolean(record?.retryable ?? true),
        at: String(record?.at ?? nowIso()),
      };
      useSocketStore.getState().setSystemError(error);
      this.emitLocal(SOCKET_EVENTS.systemError, error);
    });

    socket.on(SOCKET_EVENTS.agentStatusUpdated, (payload: unknown) => {
      const record = asRecord(payload);
      if (!record) {
        return;
      }

      const mapped: AgentStatusUpdatedPayload = {
        agentId: String(record.agentId ?? record.agent_id ?? record.id ?? ""),
        status: (record.status ??
          "idle") as AgentStatusUpdatedPayload["status"],
        currentTask: String(
          record.currentTask ?? record.current_task ?? record.task ?? ""
        ),
        cpuPercent:
          typeof record.cpuPercent === "number"
            ? record.cpuPercent
            : typeof record.cpu_percent === "number"
              ? record.cpu_percent
              : undefined,
        memoryMb:
          typeof record.memoryMb === "number"
            ? record.memoryMb
            : typeof record.memory_mb === "number"
              ? record.memory_mb
              : undefined,
        agent: asRecord(record.agent) ?? undefined,
      };

      if (!mapped.agentId) {
        return;
      }

      useSocketStore.getState().upsertAgentStatus(mapped);
      this.emitLocal(SOCKET_EVENTS.agentStatusUpdated, mapped);
    });

    for (const event of FORWARDED_EVENTS) {
      socket.on(event, (payload: unknown) => {
        this.emitLocal(event, payload as SocketPayloadMap[typeof event]);
      });
    }
  }

  private async handleAuthFailure(): Promise<void> {
    const token = await refreshAccessToken();
    if (!token) {
      useSocketStore.getState().setStatus("auth_failed");
      return;
    }

    if (!this.socket) {
      this.connect();
      return;
    }

    this.socket.auth = { token };
    if (this.socket.connected) {
      this.socket.emit(SOCKET_EVENTS.authenticate, { token });
      return;
    }

    this.socket.connect();
  }

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.heartbeatTimer = setInterval(() => {
      if (!this.socket?.connected) {
        return;
      }

      this.lastPingAt = Date.now();
      this.socket.emit(SOCKET_EVENTS.ping, { at: nowIso() });
      this.emitLocal(SOCKET_EVENTS.ping, { at: nowIso() });
      this.socket.emit(SOCKET_EVENTS.heartbeat, { at: nowIso() });

      this.clearPongTimer();
      this.pongTimer = setTimeout(() => {
        useSocketStore.getState().setLastError("WebSocket heartbeat timed out.");
        useSocketStore.getState().setStatus("reconnecting");
        this.socket?.disconnect();
        this.socket?.connect();
      }, PONG_TIMEOUT_MS);
    }, HEARTBEAT_INTERVAL_MS);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  private clearPongTimer(): void {
    if (this.pongTimer) {
      clearTimeout(this.pongTimer);
      this.pongTimer = null;
    }
  }

  private emitLocal<E extends keyof SocketPayloadMap>(
    event: E,
    payload: SocketPayloadMap[E]
  ): void {
    const bucket = this.localListeners.get(String(event));
    if (!bucket) {
      return;
    }

    for (const listener of bucket) {
      listener(payload);
    }
  }
}

export const socketManager = SocketManager.getInstance();
export const socketClient = socketManager;
