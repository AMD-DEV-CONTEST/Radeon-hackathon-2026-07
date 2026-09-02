"use client";

import type {
  AdminAnalytics,
  AdminDashboard,
  AdminInterviewsResponse,
  AdminSystemResponse,
  AdminUsersResponse,
} from "@/features/admin/types/admin.types";
import {
  mapAdminAnalytics,
  mapAdminDashboard,
  mapAdminInterviews,
  mapAdminSystem,
  mapAdminUsers,
} from "@/features/admin/utils/admin-mappers";
import { api } from "@/services/api/client";

export const adminService = {
  async getDashboard(): Promise<AdminDashboard> {
    const data = await api.get<unknown>("/admin/dashboard");
    return mapAdminDashboard(data);
  },

  async getAnalytics(): Promise<AdminAnalytics> {
    const data = await api.get<unknown>("/admin/analytics");
    return mapAdminAnalytics(data);
  },

  async getUsers(): Promise<AdminUsersResponse> {
    const data = await api.get<unknown>("/admin/users");
    return mapAdminUsers(data);
  },

  async getInterviews(): Promise<AdminInterviewsResponse> {
    const data = await api.get<unknown>("/admin/interviews");
    return mapAdminInterviews(data);
  },

  async getSystem(): Promise<AdminSystemResponse> {
    const data = await api.get<unknown>("/admin/system");
    return mapAdminSystem(data);
  },
};
