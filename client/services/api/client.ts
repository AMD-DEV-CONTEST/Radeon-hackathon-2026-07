"use client";

/**
 * Backward-compatible entrypoint.
 * Prefer `@/services/api/axios` or `@/services/api/api-client` for new code.
 */
export { apiClient, axiosInstance } from "@/services/api/axios";
export { api } from "@/services/api/api-client";
export type { ApiClient, ApiRequestOptions, ApiUploadOptions } from "@/services/api/api-client";
