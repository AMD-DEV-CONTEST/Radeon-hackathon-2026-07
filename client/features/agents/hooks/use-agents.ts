"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { AGENTS_QUERY_KEYS } from "@/features/agents/constants/agents-keys";
import { agentsService } from "@/features/agents/services/agents.service";
import {
  getAgentsErrorMessage,
  getAgentsLogsErrorMessage,
  getAgentsMetricsErrorMessage,
  getAgentsStatusErrorMessage,
  isNotFoundError,
} from "@/features/agents/utils/agents-errors";
import { mergeAgentsOverview } from "@/features/agents/utils/agents-mappers";
import { useAgentStatus } from "@/hooks/useAgentStatus";

export { useOrchestration } from "@/features/agents/hooks/use-orchestration";
export { useWorkflow } from "@/features/agents/hooks/use-workflow";

export const agentsQueryKeys = AGENTS_QUERY_KEYS;

export function useAgents() {
  return useQuery({
    queryKey: AGENTS_QUERY_KEYS.overview(),
    queryFn: () => agentsService.getAgents(),
    retry: 1,
    staleTime: 15_000,
    refetchInterval: 15_000,
  });
}

export function useAgentsStatus() {
  return useQuery({
    queryKey: AGENTS_QUERY_KEYS.status(),
    queryFn: () => agentsService.getAgentsStatus(),
    retry: 1,
    staleTime: 10_000,
    refetchInterval: 10_000,
  });
}

export function useAgentsLogs() {
  return useQuery({
    queryKey: AGENTS_QUERY_KEYS.logs(),
    queryFn: () => agentsService.getAgentsLogs(),
    retry: 1,
    staleTime: 10_000,
    refetchInterval: 10_000,
  });
}

export function useAgentsMetrics() {
  return useQuery({
    queryKey: AGENTS_QUERY_KEYS.metrics(),
    queryFn: () => agentsService.getAgentsMetrics(),
    retry: 1,
    staleTime: 10_000,
    refetchInterval: 10_000,
  });
}

export function useAgentsMonitor() {
  const overviewQuery = useAgents();
  const statusQuery = useAgentsStatus();
  const logsQuery = useAgentsLogs();
  const metricsQuery = useAgentsMetrics();
  const agentStatus = useAgentStatus({ enabled: true });

  const data = useMemo(() => {
    if (!overviewQuery.data) {
      return undefined;
    }

    return mergeAgentsOverview({
      overview: overviewQuery.data,
      status: statusQuery.data ?? null,
      metrics: metricsQuery.data ?? null,
    });
  }, [overviewQuery.data, statusQuery.data, metricsQuery.data]);

  return {
    data,
    logs: logsQuery.data?.logs ?? [],
    overviewQuery,
    statusQuery,
    logsQuery,
    metricsQuery,
    agentStatus,
    isLoading: overviewQuery.isLoading,
    isFetching:
      overviewQuery.isFetching ||
      statusQuery.isFetching ||
      logsQuery.isFetching ||
      metricsQuery.isFetching,
    isError: overviewQuery.isError,
    error: overviewQuery.error,
    refetch: async () => {
      agentStatus.retry();
      await Promise.all([
        overviewQuery.refetch(),
        statusQuery.refetch(),
        logsQuery.refetch(),
        metricsQuery.refetch(),
      ]);
    },
  };
}

export {
  getAgentsErrorMessage,
  getAgentsLogsErrorMessage,
  getAgentsMetricsErrorMessage,
  getAgentsStatusErrorMessage,
  isNotFoundError,
};
