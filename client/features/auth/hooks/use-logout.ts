"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";

import { AUTH_MUTATION_KEYS, AUTH_QUERY_KEYS } from "@/features/auth/constants/auth-keys";
import { authService } from "@/features/auth/services/auth.service";
import { useAuthStore } from "@/features/auth/store/auth.store";
import {
  getAuthErrorMessage,
} from "@/features/auth/utils/auth-errors";

export function useLogout() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const refreshToken = useAuthStore((state) => state.refreshToken);
  const clearAuth = useAuthStore((state) => state.clearAuth);

  return useMutation({
    mutationKey: AUTH_MUTATION_KEYS.logout,
    retry: false,
    mutationFn: async () => {
      return authService.logout({ refreshToken });
    },
    onSettled: async () => {
      clearAuth();
      queryClient.removeQueries({ queryKey: AUTH_QUERY_KEYS.currentUser });
      await queryClient.cancelQueries({ queryKey: AUTH_QUERY_KEYS.currentUser });
      router.replace("/login");
    },
  });
}

export function getLogoutErrorMessage(error: unknown): string {
  return getAuthErrorMessage(error);
}
