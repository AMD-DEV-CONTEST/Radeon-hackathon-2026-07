"use client";

import axios, {
  type AxiosError,
  type AxiosInstance,
  type InternalAxiosRequestConfig,
} from "axios";

import { env } from "@/config/env";
import { useAuthStore } from "@/features/auth/store/auth.store";
import type { BackendTokenDto } from "@/features/auth/utils/auth-mappers";
import { mapBackendTokens } from "@/features/auth/utils/auth-mappers";
import { toApiRequestError } from "@/services/api/errors";

interface RetryConfig extends InternalAxiosRequestConfig {
  _retry?: boolean;
}

const AUTH_SKIP_REFRESH_PATHS = [
  "/auth/login",
  "/auth/register",
  "/auth/refresh",
  "/auth/forgot-password",
  "/auth/logout",
] as const;

let refreshPromise: Promise<string | null> | null = null;

function shouldSkipTokenRefresh(url: string | undefined): boolean {
  if (!url) {
    return false;
  }

  return AUTH_SKIP_REFRESH_PATHS.some((path) => url.includes(path));
}

/**
 * Dedicated client for token refresh — no auth interceptors — to avoid loops.
 */
const refreshClient = axios.create({
  baseURL: env.apiBaseUrl,
  timeout: 15_000,
  headers: {
    "Content-Type": "application/json",
    Accept: "application/json",
  },
});

/** Shared JWT refresh used by Axios interceptors and the WebSocket layer. */
export async function refreshAccessToken(): Promise<string | null> {
  const { refreshToken, setTokens, clearAuth } = useAuthStore.getState();

  if (!refreshToken) {
    clearAuth();
    return null;
  }

  try {
    const { data } = await refreshClient.post<BackendTokenDto>(
      "/auth/refresh",
      { refresh_token: refreshToken }
    );

    const tokens = mapBackendTokens(data);
    setTokens(tokens);

    return tokens.accessToken;
  } catch {
    clearAuth();
    return null;
  }
}

function attachAuthorizationHeader(
  config: InternalAxiosRequestConfig
): InternalAxiosRequestConfig {
  const { accessToken } = useAuthStore.getState();

  if (accessToken) {
    config.headers.set("Authorization", `Bearer ${accessToken}`);
  }

  // Let the browser set multipart boundaries automatically.
  if (typeof FormData !== "undefined" && config.data instanceof FormData) {
    config.headers.delete("Content-Type");
  }

  return config;
}

async function handleUnauthorized(
  client: AxiosInstance,
  error: AxiosError
): Promise<unknown> {
  const originalRequest = error.config as RetryConfig | undefined;

  if (
    !originalRequest ||
    error.response?.status !== 401 ||
    originalRequest._retry ||
    shouldSkipTokenRefresh(originalRequest.url)
  ) {
    return Promise.reject(toApiRequestError(error));
  }

  originalRequest._retry = true;

  refreshPromise ??= refreshAccessToken().finally(() => {
    refreshPromise = null;
  });

  const accessToken = await refreshPromise;

  if (!accessToken) {
    return Promise.reject(toApiRequestError(error));
  }

  originalRequest.headers.set("Authorization", `Bearer ${accessToken}`);
  return client(originalRequest);
}

function createAxiosInstance(): AxiosInstance {
  const instance = axios.create({
    baseURL: env.apiBaseUrl,
    timeout: 30_000,
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
    },
  });

  instance.interceptors.request.use(
    (config) => attachAuthorizationHeader(config),
    (error: unknown) => Promise.reject(toApiRequestError(error))
  );

  instance.interceptors.response.use(
    (response) => response,
    async (error: AxiosError) => {
      if (error.response?.status === 401) {
        return handleUnauthorized(instance, error);
      }

      return Promise.reject(toApiRequestError(error));
    }
  );

  return instance;
}

/** Production Axios instance with JWT injection and refresh-token flow. */
export const axiosInstance = createAxiosInstance();

/** @deprecated Prefer importing `axiosInstance` or helpers from `api-client`. */
export const apiClient = axiosInstance;
