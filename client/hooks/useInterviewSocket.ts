"use client";

import { useEffect, useRef } from "react";

import { useInterviewStore } from "@/features/interview/store/interview.store";
import { SOCKET_EVENTS } from "@/services/websocket/events";
import { interviewSocket } from "@/services/websocket/interview.socket";
import { useSocketStore } from "@/services/websocket/socket.store";

export function useInterviewSocket(interviewId: string | undefined) {
  const intentionalDisconnectRef = useRef(false);

  const setSocketConnected = useInterviewStore(
    (state) => state.setSocketConnected
  );
  const setMetrics = useInterviewStore((state) => state.setMetrics);
  const setLatency = useInterviewStore((state) => state.setLatency);
  const setPhase = useInterviewStore((state) => state.setPhase);
  const setQuestion = useInterviewStore((state) => state.setQuestion);
  const setProgress = useInterviewStore((state) => state.setProgress);
  const upsertAgent = useInterviewStore((state) => state.upsertAgent);
  const endSession = useInterviewStore((state) => state.endSession);
  const isConnected = useInterviewStore((state) => state.isSocketConnected);
  const socketStatus = useSocketStore((state) => state.status);
  const socketLatency = useSocketStore((state) => state.latencyMs);

  useEffect(() => {
    if (!interviewId) {
      return;
    }

    intentionalDisconnectRef.current = false;
    interviewSocket.connect(interviewId);
    setSocketConnected(true);

    const unsubscribers = [
      interviewSocket.on(SOCKET_EVENTS.connect, () => {
        setSocketConnected(true);
        if (useInterviewStore.getState().phase === "connection_lost") {
          setPhase("live");
        }
      }),
      interviewSocket.on(SOCKET_EVENTS.reconnect, () => {
        setSocketConnected(true);
        setPhase("live");
      }),
      interviewSocket.on(SOCKET_EVENTS.disconnect, () => {
        setSocketConnected(false);
        if (!intentionalDisconnectRef.current) {
          setPhase("connection_lost");
        }
      }),
      interviewSocket.on(SOCKET_EVENTS.connectError, () => {
        setSocketConnected(false);
        if (!intentionalDisconnectRef.current) {
          setPhase("connection_lost");
        }
      }),
      interviewSocket.on(SOCKET_EVENTS.authError, () => {
        setSocketConnected(false);
        setPhase("connection_lost");
      }),
      interviewSocket.on(SOCKET_EVENTS.interviewStarted, () => {
        setPhase("live");
      }),
      interviewSocket.on(SOCKET_EVENTS.interviewEnded, (payload) => {
        if (payload.interviewId !== interviewId) {
          return;
        }
        endSession();
      }),
      interviewSocket.on(SOCKET_EVENTS.questionChanged, (payload) => {
        if (payload.interviewId !== interviewId) {
          return;
        }
        setQuestion(payload.question);
      }),
      interviewSocket.on(SOCKET_EVENTS.evaluationUpdated, (payload) => {
        if (payload.interviewId !== interviewId) {
          return;
        }
        setMetrics(payload.metrics);
        if (typeof payload.latencyMs === "number") {
          setLatency(payload.latencyMs);
        }
      }),
      interviewSocket.on(SOCKET_EVENTS.progressUpdated, (payload) => {
        if (payload.interviewId !== interviewId) {
          return;
        }
        setProgress(
          payload.progressPercent,
          payload.estimatedRemainingLabel
        );
      }),
      interviewSocket.on(SOCKET_EVENTS.agentStatusUpdated, (payload) => {
        upsertAgent({
          id: String(payload.agentId),
          currentTask: payload.currentTask,
          status:
            payload.status === "running" || payload.status === "busy"
              ? "active"
              : payload.status === "completed"
                ? "completed"
                : "waiting",
          name:
            typeof payload.agent?.name === "string"
              ? payload.agent.name
              : undefined,
        });
      }),
      interviewSocket.on(SOCKET_EVENTS.pong, (payload) => {
        setLatency(payload.latencyMs);
      }),
    ];

    return () => {
      intentionalDisconnectRef.current = true;
      for (const unsubscribe of unsubscribers) {
        unsubscribe();
      }
      interviewSocket.disconnect();
      setSocketConnected(false);
    };
  }, [
    endSession,
    interviewId,
    setLatency,
    setMetrics,
    setPhase,
    setProgress,
    setQuestion,
    setSocketConnected,
    upsertAgent,
  ]);

  useEffect(() => {
    if (socketLatency > 0) {
      setLatency(socketLatency);
    }
  }, [setLatency, socketLatency]);

  return {
    isConnected: isConnected || socketStatus === "connected",
    status: socketStatus,
    latencyMs: socketLatency,
    socket: interviewSocket,
    retry: () => {
      if (!interviewId) {
        return;
      }
      interviewSocket.disconnect();
      interviewSocket.connect(interviewId);
    },
  };
}
