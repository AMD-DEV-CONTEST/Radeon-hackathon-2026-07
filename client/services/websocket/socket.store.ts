"use client";

import { create } from "zustand";

import type {
  AgentStatusUpdatedPayload,
  SocketConnectionStatus,
  SocketNotificationPayload,
  SocketSystemErrorPayload,
} from "@/services/websocket/events";

interface SocketState {
  status: SocketConnectionStatus;
  isConnected: boolean;
  latencyMs: number;
  reconnectAttempt: number;
  lastError: string | null;
  lastNotification: SocketNotificationPayload | null;
  lastSystemError: SocketSystemErrorPayload | null;
  agentStatuses: Record<string, AgentStatusUpdatedPayload>;
  setStatus: (status: SocketConnectionStatus) => void;
  setLatency: (latencyMs: number) => void;
  setReconnectAttempt: (attempt: number) => void;
  setLastError: (message: string | null) => void;
  setNotification: (notification: SocketNotificationPayload | null) => void;
  setSystemError: (error: SocketSystemErrorPayload | null) => void;
  upsertAgentStatus: (payload: AgentStatusUpdatedPayload) => void;
  reset: () => void;
}

const initialState = {
  status: "idle" as SocketConnectionStatus,
  isConnected: false,
  latencyMs: 0,
  reconnectAttempt: 0,
  lastError: null,
  lastNotification: null,
  lastSystemError: null,
  agentStatuses: {},
};

export const useSocketStore = create<SocketState>((set) => ({
  ...initialState,
  setStatus: (status) => {
    set({
      status,
      isConnected: status === "connected",
    });
  },
  setLatency: (latencyMs) => {
    set({ latencyMs });
  },
  setReconnectAttempt: (attempt) => {
    set({ reconnectAttempt: attempt });
  },
  setLastError: (message) => {
    set({ lastError: message });
  },
  setNotification: (notification) => {
    set({ lastNotification: notification });
  },
  setSystemError: (error) => {
    set({
      lastSystemError: error,
      lastError: error?.message ?? null,
    });
  },
  upsertAgentStatus: (payload) => {
    set((state) => ({
      agentStatuses: {
        ...state.agentStatuses,
        [String(payload.agentId)]: payload,
      },
    }));
  },
  reset: () => {
    set(initialState);
  },
}));
