"use client";

import {
  SOCKET_EVENTS,
  type AgentStatusUpdatedPayload,
} from "@/services/websocket/events";
import { socketManager } from "@/services/websocket/socket";

type SocketListener<T> = (payload: T) => void;

class AgentSocketClient {
  private static instance: AgentSocketClient | null = null;
  private joined = false;

  static getInstance(): AgentSocketClient {
    AgentSocketClient.instance ??= new AgentSocketClient();
    return AgentSocketClient.instance;
  }

  isJoined(): boolean {
    return this.joined;
  }

  join(): void {
    if (this.joined) {
      return;
    }
    socketManager.connect();
    socketManager.emit(SOCKET_EVENTS.joinAgents, {
      at: new Date().toISOString(),
    });
    this.joined = true;
  }

  leave(): void {
    if (!this.joined) {
      return;
    }
    socketManager.emit(SOCKET_EVENTS.leaveAgents, {
      at: new Date().toISOString(),
    });
    socketManager.release();
    this.joined = false;
  }

  onStatusUpdated(
    listener: SocketListener<AgentStatusUpdatedPayload>
  ): () => void {
    return socketManager.on(SOCKET_EVENTS.agentStatusUpdated, listener);
  }
}

export const agentSocket = AgentSocketClient.getInstance();
