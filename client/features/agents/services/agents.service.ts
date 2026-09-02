"use client";

import type {
  AgentsLogsResponse,
  AgentsMetricsResponse,
  AgentsOverview,
  AgentsStatusResponse,
} from "@/features/agents/types/agents.types";
import {
  mapAgentsLogs,
  mapAgentsMetrics,
  mapAgentsOverview,
  mapAgentsStatus,
} from "@/features/agents/utils/agents-mappers";
import { api } from "@/services/api/client";

export const agentsService = {
  async getAgents(): Promise<AgentsOverview> {
    const data = await api.get<unknown>("/agents");
    return mapAgentsOverview(data);
  },

  async getAgentsStatus(): Promise<AgentsStatusResponse> {
    const data = await api.get<unknown>("/agents/status");
    return mapAgentsStatus(data);
  },

  async getAgentsLogs(): Promise<AgentsLogsResponse> {
    const data = await api.get<unknown>("/agents/logs");
    return mapAgentsLogs(data);
  },

  async getAgentsMetrics(): Promise<AgentsMetricsResponse> {
    const data = await api.get<unknown>("/agents/metrics");
    return mapAgentsMetrics(data);
  },
};
