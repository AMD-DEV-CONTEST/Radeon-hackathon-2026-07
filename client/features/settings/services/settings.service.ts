"use client";

import {
  MOCK_USER_SETTINGS,
  simulateNetworkLatency,
} from "@/features/settings/data/mock-settings";
import type {
  DeviceSettings,
  UpdateSettingsPayload,
  UserProfileSettings,
  UserSettings,
} from "@/features/settings/types/settings.types";
import { apiClient } from "@/services/api/client";

const useMockApi = process.env.NEXT_PUBLIC_USE_MOCK_API !== "false";

let mockSettingsState: UserSettings = structuredClone(MOCK_USER_SETTINGS);

export const settingsService = {
  async getSettings(): Promise<UserSettings> {
    if (useMockApi) {
      await simulateNetworkLatency();
      return structuredClone(mockSettingsState);
    }

    const { data } = await apiClient.get<UserSettings>("/settings");
    return data;
  },

  async updateSettings(payload: UpdateSettingsPayload): Promise<UserSettings> {
    if (useMockApi) {
      await simulateNetworkLatency(420);
      mockSettingsState = {
        ...mockSettingsState,
        profile: { ...mockSettingsState.profile, ...payload.profile },
        interview: { ...mockSettingsState.interview, ...payload.interview },
        notifications: {
          ...mockSettingsState.notifications,
          ...payload.notifications,
        },
        appearance: { ...mockSettingsState.appearance, ...payload.appearance },
        security: { ...mockSettingsState.security, ...payload.security },
        devices: {
          ...mockSettingsState.devices,
          ...payload.devices,
        },
        ai: { ...mockSettingsState.ai, ...payload.ai },
        apiKeys: { ...mockSettingsState.apiKeys, ...payload.apiKeys },
        updatedAt: new Date().toISOString(),
      };
      return structuredClone(mockSettingsState);
    }

    const { data } = await apiClient.put<UserSettings>("/settings", payload);
    return data;
  },

  async getDevices(): Promise<DeviceSettings> {
    if (useMockApi) {
      await simulateNetworkLatency(220);
      return structuredClone(mockSettingsState.devices);
    }

    const { data } = await apiClient.get<DeviceSettings>("/devices");
    return data;
  },

  async getProfile(): Promise<UserProfileSettings> {
    if (useMockApi) {
      await simulateNetworkLatency(200);
      return structuredClone(mockSettingsState.profile);
    }

    const { data } = await apiClient.get<UserProfileSettings>("/profile");
    return data;
  },

  async revokeSession(sessionId: string): Promise<UserSettings> {
    if (useMockApi) {
      await simulateNetworkLatency(260);
      mockSettingsState = {
        ...mockSettingsState,
        sessions: mockSettingsState.sessions.filter(
          (session) => session.id !== sessionId
        ),
        updatedAt: new Date().toISOString(),
      };
      return structuredClone(mockSettingsState);
    }

    const { data } = await apiClient.delete<UserSettings>(
      `/settings/sessions/${sessionId}`
    );
    return data;
  },

  async logoutAllDevices(): Promise<UserSettings> {
    if (useMockApi) {
      await simulateNetworkLatency(300);
      mockSettingsState = {
        ...mockSettingsState,
        sessions: mockSettingsState.sessions.filter(
          (session) => session.isCurrent
        ),
        updatedAt: new Date().toISOString(),
      };
      return structuredClone(mockSettingsState);
    }

    const { data } = await apiClient.post<UserSettings>(
      "/settings/sessions/logout-all"
    );
    return data;
  },

  async resetPreferences(): Promise<UserSettings> {
    if (useMockApi) {
      await simulateNetworkLatency(320);
      mockSettingsState = structuredClone(MOCK_USER_SETTINGS);
      return structuredClone(mockSettingsState);
    }

    const { data } = await apiClient.post<UserSettings>(
      "/settings/reset-preferences"
    );
    return data;
  },

  async deleteAccount(): Promise<{ success: true }> {
    if (useMockApi) {
      await simulateNetworkLatency(400);
      return { success: true };
    }

    await apiClient.delete("/settings/account");
    return { success: true };
  },
};
