"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";

import { AUTH_QUERY_KEYS } from "@/features/auth/constants/auth-keys";
import { authService } from "@/features/auth/services/auth.service";
import { useAuthStore } from "@/features/auth/store/auth.store";
import { normalizeApiError } from "@/services/api/errors";

interface UseCurrentUserOptions {
  enabled?: boolean;
}

export function useCurrentUser(options: UseCurrentUserOptions = {}) {
  const accessToken = useAuthStore((state) => state.accessToken);
  const setUser = useAuthStore((state) => state.setUser);
  const clearAuth = useAuthStore((state) => state.clearAuth);

  const enabled = (options.enabled ?? true) && Boolean(accessToken);

  const query = useQuery({
    queryKey: AUTH_QUERY_KEYS.currentUser,
    queryFn: () => authService.getMe(),
    enabled,
    retry: false,
    staleTime: 60_000,
  });

  useEffect(() => {
    if (query.data) {
      setUser(query.data);
    }
  }, [query.data, setUser]);

  useEffect(() => {
    if (!query.error) {
      return;
    }

    const normalized = normalizeApiError(query.error);
    if (normalized.isUnauthorized) {
      clearAuth();
    }
  }, [query.error, clearAuth]);

  return query;
}
