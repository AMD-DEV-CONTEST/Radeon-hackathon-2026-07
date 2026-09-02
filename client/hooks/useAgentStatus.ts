"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo } from "react";

import { AGENTS_QUERY_KEYS } from "@/features/agents/constants/agents-keys";
import type {
  AgentCardData,
  AgentRuntimeStatus,
  AgentsOverview,
  WorkflowNodeId,
} from "@/features/agents/types/agents.types";
import { agentSocket } from "@/services/websocket/agent.socket";
import { useSocketStore } from "@/services/websocket/socket.store";

function isWorkflowNodeId(value: string): value is WorkflowNodeId {
  return (
    value === "resume" ||
    value === "planner" ||
    value === "technical" ||
    value === "behavior" ||
    value === "factChecker" ||
    value === "evaluation" ||
    value === "hiring"
  );
}

function toRuntimeStatus(value: string): AgentRuntimeStatus {
  if (
    value === "idle" ||
    value === "running" ||
    value === "busy" ||
    value === "waiting" ||
    value === "error" ||
    value === "completed"
  ) {
    return value;
  }
  if (value === "active") {
    return "running";
  }
  return "idle";
}

interface UseAgentStatusOptions {
  enabled?: boolean;
}

export function useAgentStatus(options: UseAgentStatusOptions = {}) {
  const enabled = options.enabled ?? true;
  const queryClient = useQueryClient();

  const agentStatuses = useSocketStore((state) => state.agentStatuses);
  const isConnected = useSocketStore((state) => state.isConnected);
  const status = useSocketStore((state) => state.status);
  const latencyMs = useSocketStore((state) => state.latencyMs);

  useEffect(() => {
    if (!enabled) {
      return;
    }

    agentSocket.join();

    const unsubscribe = agentSocket.onStatusUpdated((payload) => {
      queryClient.setQueryData<AgentsOverview>(
        AGENTS_QUERY_KEYS.overview(),
        (current) => {
          if (!current) {
            return current;
          }

          const agentId = String(payload.agentId);
          if (!isWorkflowNodeId(agentId)) {
            return current;
          }

          const nextStatus = toRuntimeStatus(String(payload.status));
          const agents = current.agents.map((agent) => {
            if (agent.id !== agentId) {
              return agent;
            }

            const next: AgentCardData = {
              ...agent,
              status: nextStatus,
              currentTask: payload.currentTask || agent.currentTask,
              cpuPercent: payload.cpuPercent ?? agent.cpuPercent,
              memoryMb: payload.memoryMb ?? agent.memoryMb,
              lastUpdated: "just now",
            };
            return next;
          });

          const workflow = current.workflow.map((node) =>
            node.id === agentId
              ? {
                  ...node,
                  status: nextStatus,
                }
              : node
          );

          return {
            ...current,
            agents,
            workflow,
            activeNodeId:
              nextStatus === "running" || nextStatus === "busy"
                ? agentId
                : current.activeNodeId,
            lastSyncedAt: new Date().toISOString(),
          };
        }
      );

      void queryClient.invalidateQueries({
        queryKey: AGENTS_QUERY_KEYS.status(),
      });
    });

    return () => {
      unsubscribe();
      agentSocket.leave();
    };
  }, [enabled, queryClient]);

  const liveAgents = useMemo(
    () => Object.values(agentStatuses),
    [agentStatuses]
  );

  return {
    isConnected,
    status,
    latencyMs,
    liveAgents,
    agentStatuses,
    retry: () => {
      agentSocket.leave();
      agentSocket.join();
    },
  };
}
