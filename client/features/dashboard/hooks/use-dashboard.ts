"use client";

import { useQuery } from "@tanstack/react-query";

import { DASHBOARD_QUERY_KEYS } from "@/features/dashboard/constants/dashboard-keys";
import { dashboardService } from "@/features/dashboard/services/dashboard.service";
import {
  getDashboardErrorMessage,
  getDashboardInterviewsErrorMessage,
  getDashboardReportsErrorMessage,
} from "@/features/dashboard/utils/dashboard-errors";

export const dashboardQueryKeys = DASHBOARD_QUERY_KEYS;

export function useDashboard() {
  return useQuery({
    queryKey: DASHBOARD_QUERY_KEYS.root(),
    queryFn: () => dashboardService.getDashboard(),
    retry: 1,
    staleTime: 30_000,
  });
}

export function useDashboardCandidate(candidateId: string) {
  return useQuery({
    queryKey: DASHBOARD_QUERY_KEYS.candidate(candidateId),
    queryFn: () => dashboardService.getCandidate(candidateId),
    enabled: candidateId.length > 0,
    retry: 1,
    staleTime: 30_000,
  });
}

export function useDashboardInterviews() {
  return useQuery({
    queryKey: DASHBOARD_QUERY_KEYS.interviews(),
    queryFn: () => dashboardService.getInterviews(),
    retry: 1,
    staleTime: 30_000,
  });
}

export function useDashboardReports() {
  return useQuery({
    queryKey: DASHBOARD_QUERY_KEYS.reports(),
    queryFn: () => dashboardService.getReports(),
    retry: 1,
    staleTime: 30_000,
  });
}

export function getUseDashboardErrorMessage(error: unknown): string {
  return getDashboardErrorMessage(error);
}

export function getUseDashboardInterviewsErrorMessage(error: unknown): string {
  return getDashboardInterviewsErrorMessage(error);
}

export function getUseDashboardReportsErrorMessage(error: unknown): string {
  return getDashboardReportsErrorMessage(error);
}
