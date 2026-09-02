"use client";

import type {
  CandidateDashboard,
  DashboardCandidate,
  DashboardInterviewListItem,
  DashboardReportListItem,
} from "@/features/dashboard/types/dashboard.types";
import {
  mapCandidateDashboard,
  mapDashboardCandidate,
  mapInterviewList,
  mapReportList,
} from "@/features/dashboard/utils/dashboard-mappers";
import { api } from "@/services/api/client";

export const dashboardService = {
  async getDashboard(): Promise<CandidateDashboard> {
    const data = await api.get<unknown>("/dashboard");
    return mapCandidateDashboard(data);
  },

  async getCandidate(id: string): Promise<DashboardCandidate> {
    const data = await api.get<unknown>(`/candidate/${id}`);
    return mapDashboardCandidate(data);
  },

  async getInterviews(): Promise<ReadonlyArray<DashboardInterviewListItem>> {
    const data = await api.get<unknown>("/interviews", {
      params: { limit: 100 },
    });
    return mapInterviewList(data);
  },

  async getReports(): Promise<ReadonlyArray<DashboardReportListItem>> {
    const data = await api.get<unknown>("/reports", {
      params: { limit: 100 },
    });
    return mapReportList(data);
  },
};
