"use client";

import type {
  AxiosRequestConfig,
  AxiosResponse,
  Method,
  ResponseType,
} from "axios";

import { axiosInstance } from "@/services/api/axios";

export interface ApiRequestOptions<TBody = unknown> {
  /** Request body for POST/PUT/PATCH. */
  data?: TBody;
  /** URL query parameters. */
  params?: Record<string, string | number | boolean | null | undefined>;
  /** Abort signal for cancellation. */
  signal?: AbortSignal;
  /** Override request headers. */
  headers?: Record<string, string>;
  /** Override timeout in milliseconds. */
  timeout?: number;
  /** Axios response type (e.g. blob for downloads). */
  responseType?: ResponseType;
  /** Extra Axios config when needed. */
  config?: Omit<
    AxiosRequestConfig,
    "url" | "method" | "data" | "params" | "signal" | "headers" | "timeout" | "responseType"
  >;
}

export interface ApiUploadOptions
  extends Omit<ApiRequestOptions<FormData>, "data"> {
  /** Form field name for the primary file. Defaults to `file`. */
  fileField?: string;
  /** Extra multipart fields. */
  fields?: Record<string, string | Blob>;
  /** Upload progress callback (0–100). */
  onUploadProgress?: (progressPercent: number) => void;
}

function buildConfig<TBody>(
  options: ApiRequestOptions<TBody> = {}
): AxiosRequestConfig {
  return {
    ...options.config,
    params: options.params,
    data: options.data,
    signal: options.signal,
    headers: options.headers,
    timeout: options.timeout,
    responseType: options.responseType,
  };
}

async function request<TResponse, TBody = unknown>(
  method: Method,
  url: string,
  options: ApiRequestOptions<TBody> = {}
): Promise<TResponse> {
  const response: AxiosResponse<TResponse> = await axiosInstance.request({
    method,
    url,
    ...buildConfig(options),
  });

  return response.data;
}

export const api = {
  get<TResponse>(
    url: string,
    options?: Omit<ApiRequestOptions, "data">
  ): Promise<TResponse> {
    return request<TResponse>("GET", url, options);
  },

  post<TResponse, TBody = unknown>(
    url: string,
    data?: TBody,
    options?: Omit<ApiRequestOptions<TBody>, "data">
  ): Promise<TResponse> {
    return request<TResponse, TBody>("POST", url, { ...options, data });
  },

  put<TResponse, TBody = unknown>(
    url: string,
    data?: TBody,
    options?: Omit<ApiRequestOptions<TBody>, "data">
  ): Promise<TResponse> {
    return request<TResponse, TBody>("PUT", url, { ...options, data });
  },

  patch<TResponse, TBody = unknown>(
    url: string,
    data?: TBody,
    options?: Omit<ApiRequestOptions<TBody>, "data">
  ): Promise<TResponse> {
    return request<TResponse, TBody>("PATCH", url, { ...options, data });
  },

  delete<TResponse, TBody = unknown>(
    url: string,
    options?: ApiRequestOptions<TBody>
  ): Promise<TResponse> {
    return request<TResponse, TBody>("DELETE", url, options);
  },

  /**
   * Multipart upload helper. Builds FormData and clears Content-Type so the
   * browser can set the multipart boundary.
   */
  upload<TResponse>(
    url: string,
    file: Blob | File,
    options: ApiUploadOptions = {}
  ): Promise<TResponse> {
    const formData = new FormData();
    const fileField = options.fileField ?? "file";
    formData.append(fileField, file);

    if (options.fields) {
      for (const [key, value] of Object.entries(options.fields)) {
        formData.append(key, value);
      }
    }

    return request<TResponse, FormData>("POST", url, {
      ...options,
      data: formData,
      headers: {
        ...options.headers,
      },
      config: {
        ...options.config,
        onUploadProgress: options.onUploadProgress
          ? (event) => {
              if (!event.total || event.total <= 0) {
                return;
              }
              const percent = Math.round((event.loaded / event.total) * 100);
              options.onUploadProgress?.(percent);
            }
          : undefined,
      },
    });
  },

  /** Exposes the underlying Axios instance when raw access is required. */
  instance: axiosInstance,
} as const;

export type ApiClient = typeof api;

export { axiosInstance, apiClient } from "@/services/api/axios";
