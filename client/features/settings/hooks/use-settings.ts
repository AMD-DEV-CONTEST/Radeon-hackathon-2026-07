"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { settingsService } from "@/features/settings/services/settings.service";
import type { UpdateSettingsPayload } from "@/features/settings/types/settings.types";

export const settingsQueryKeys = {
  all: ["settings"] as const,
  root: () => [...settingsQueryKeys.all, "root"] as const,
  profile: () => [...settingsQueryKeys.all, "profile"] as const,
  devices: () => [...settingsQueryKeys.all, "devices"] as const,
};

export function useSettings() {
  return useQuery({
    queryKey: settingsQueryKeys.root(),
    queryFn: () => settingsService.getSettings(),
    retry: 1,
    staleTime: 20_000,
  });
}

export function useSettingsProfile() {
  return useQuery({
    queryKey: settingsQueryKeys.profile(),
    queryFn: () => settingsService.getProfile(),
    retry: 1,
    staleTime: 20_000,
  });
}

export function useSettingsDevices() {
  return useQuery({
    queryKey: settingsQueryKeys.devices(),
    queryFn: () => settingsService.getDevices(),
    retry: 1,
    staleTime: 20_000,
  });
}

export function useUpdateSettings() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationKey: ["settings", "update"],
    retry: false,
    mutationFn: (payload: UpdateSettingsPayload) =>
      settingsService.updateSettings(payload),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: settingsQueryKeys.all });
    },
  });
}

export function useRevokeSession() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationKey: ["settings", "revoke-session"],
    retry: false,
    mutationFn: (sessionId: string) => settingsService.revokeSession(sessionId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: settingsQueryKeys.all });
    },
  });
}

export function useLogoutAllDevices() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationKey: ["settings", "logout-all"],
    retry: false,
    mutationFn: () => settingsService.logoutAllDevices(),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: settingsQueryKeys.all });
    },
  });
}

export function useResetPreferences() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationKey: ["settings", "reset"],
    retry: false,
    mutationFn: () => settingsService.resetPreferences(),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: settingsQueryKeys.all });
    },
  });
}

export function useDeleteAccount() {
  return useMutation({
    mutationKey: ["settings", "delete-account"],
    retry: false,
    mutationFn: () => settingsService.deleteAccount(),
  });
}
