"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { ADMIN_QUERY_KEYS } from "@/features/admin/constants/admin-keys";
import { adminService } from "@/features/admin/services/admin.service";
import {
  getAdminAnalyticsErrorMessage,
  getAdminDashboardErrorMessage,
  getAdminInterviewsErrorMessage,
  getAdminSystemErrorMessage,
  getAdminUsersErrorMessage,
  isNotFoundError,
} from "@/features/admin/utils/admin-errors";
import { mergeAdminDashboard } from "@/features/admin/utils/admin-mappers";

export const adminQueryKeys = ADMIN_QUERY_KEYS;

export function useAdminDashboard() {
  return useQuery({
    queryKey: ADMIN_QUERY_KEYS.dashboard(),
    queryFn: () => adminService.getDashboard(),
    retry: 1,
    staleTime: 20_000,
  });
}

export function useAdminAnalytics() {
  return useQuery({
    queryKey: ADMIN_QUERY_KEYS.analytics(),
    queryFn: () => adminService.getAnalytics(),
    retry: 1,
    staleTime: 20_000,
  });
}

export function useAdminUsers() {
  return useQuery({
    queryKey: ADMIN_QUERY_KEYS.users(),
    queryFn: () => adminService.getUsers(),
    retry: 1,
    staleTime: 20_000,
  });
}

export function useAdminInterviews() {
  return useQuery({
    queryKey: ADMIN_QUERY_KEYS.interviews(),
    queryFn: () => adminService.getInterviews(),
    retry: 1,
    staleTime: 20_000,
  });
}

export function useAdminSystem() {
  return useQuery({
    queryKey: ADMIN_QUERY_KEYS.system(),
    queryFn: () => adminService.getSystem(),
    retry: 1,
    staleTime: 15_000,
  });
}

export function useAdmin() {
  const dashboardQuery = useAdminDashboard();
  const analyticsQuery = useAdminAnalytics();
  const usersQuery = useAdminUsers();
  const interviewsQuery = useAdminInterviews();
  const systemQuery = useAdminSystem();

  const data = useMemo(() => {
    if (!dashboardQuery.data) {
      return undefined;
    }

    return mergeAdminDashboard({
      dashboard: dashboardQuery.data,
      analytics: analyticsQuery.data ?? null,
      users: usersQuery.data ?? null,
      interviews: interviewsQuery.data ?? null,
      system: systemQuery.data ?? null,
    });
  }, [
    dashboardQuery.data,
    analyticsQuery.data,
    usersQuery.data,
    interviewsQuery.data,
    systemQuery.data,
  ]);

  return {
    data,
    dashboardQuery,
    analyticsQuery,
    usersQuery,
    interviewsQuery,
    systemQuery,
    isLoading: dashboardQuery.isLoading,
    isFetching:
      dashboardQuery.isFetching ||
      analyticsQuery.isFetching ||
      usersQuery.isFetching ||
      interviewsQuery.isFetching ||
      systemQuery.isFetching,
    isError: dashboardQuery.isError,
    error: dashboardQuery.error,
    refetch: async () => {
      await Promise.all([
        dashboardQuery.refetch(),
        analyticsQuery.refetch(),
        usersQuery.refetch(),
        interviewsQuery.refetch(),
        systemQuery.refetch(),
      ]);
    },
  };
}

export {
  getAdminAnalyticsErrorMessage,
  getAdminDashboardErrorMessage,
  getAdminInterviewsErrorMessage,
  getAdminSystemErrorMessage,
  getAdminUsersErrorMessage,
  isNotFoundError,
};
