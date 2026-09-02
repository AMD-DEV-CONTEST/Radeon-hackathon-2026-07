"use client";

import { useEffect } from "react";

import { SOCKET_EVENTS } from "@/services/websocket/events";
import { socketManager } from "@/services/websocket/socket";
import { useSocketStore } from "@/services/websocket/socket.store";

interface UseSocketOptions {
  enabled?: boolean;
}

export function useSocket(options: UseSocketOptions = {}) {
  const enabled = options.enabled ?? true;

  const status = useSocketStore((state) => state.status);
  const isConnected = useSocketStore((state) => state.isConnected);
  const latencyMs = useSocketStore((state) => state.latencyMs);
  const reconnectAttempt = useSocketStore((state) => state.reconnectAttempt);
  const lastError = useSocketStore((state) => state.lastError);
  const lastNotification = useSocketStore((state) => state.lastNotification);
  const lastSystemError = useSocketStore((state) => state.lastSystemError);

  useEffect(() => {
    if (!enabled) {
      return;
    }

    socketManager.connect();

    const unsubscribeReconnect = socketManager.on(
      SOCKET_EVENTS.reconnect,
      () => {
        useSocketStore.getState().setStatus("connected");
      }
    );

    return () => {
      unsubscribeReconnect();
      socketManager.release();
    };
  }, [enabled]);

  return {
    status,
    isConnected,
    latencyMs,
    reconnectAttempt,
    lastError,
    lastNotification,
    lastSystemError,
    connect: () => {
      socketManager.connect();
    },
    disconnect: () => {
      socketManager.disconnect();
    },
    retry: () => {
      socketManager.disconnect();
      socketManager.connect();
    },
    reauthenticate: () => socketManager.reauthenticate(),
    socket: socketManager,
  };
}
