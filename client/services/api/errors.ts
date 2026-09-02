import { AxiosError, isAxiosError } from "axios";

export interface ApiFieldError {
  field: string;
  message: string;
}

export type ApiErrorKind =
  | "http"
  | "network"
  | "timeout"
  | "canceled"
  | "unknown";

export interface NormalizedApiError {
  message: string;
  statusCode: number | null;
  fieldErrors: ApiFieldError[];
  code: string | null;
  kind: ApiErrorKind;
  isUnauthorized: boolean;
  isNetworkError: boolean;
  isTimeoutError: boolean;
  isCanceled: boolean;
}

interface ApiErrorBody {
  message?: string;
  detail?: string | Array<{ loc?: Array<string | number>; msg?: string }>;
  code?: string;
  errors?: Record<string, string[] | string>;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value === "object" && value !== null) {
    return value as Record<string, unknown>;
  }

  return null;
}

function normalizeFieldErrors(body: ApiErrorBody | null): ApiFieldError[] {
  if (!body) {
    return [];
  }

  const fieldErrors: ApiFieldError[] = [];

  if (body.errors) {
    for (const [field, messages] of Object.entries(body.errors)) {
      if (Array.isArray(messages)) {
        for (const message of messages) {
          fieldErrors.push({ field, message });
        }
      } else {
        fieldErrors.push({ field, message: messages });
      }
    }
  }

  if (Array.isArray(body.detail)) {
    for (const item of body.detail) {
      const field = item.loc?.filter((part) => typeof part === "string").at(-1);
      if (field && item.msg) {
        fieldErrors.push({ field, message: item.msg });
      }
    }
  }

  return fieldErrors;
}

function isTimeoutError(error: AxiosError): boolean {
  return (
    error.code === "ECONNABORTED" ||
    error.code === "ETIMEDOUT" ||
    /timeout/i.test(error.message)
  );
}

function isNetworkError(error: AxiosError): boolean {
  return (
    !error.response &&
    (error.code === "ERR_NETWORK" ||
      error.message === "Network Error" ||
      error.code === "ECONNREFUSED")
  );
}

function isCanceledError(error: AxiosError): boolean {
  return (
    error.code === "ERR_CANCELED" ||
    error.name === "CanceledError" ||
    error.message === "canceled"
  );
}

export function normalizeApiError(error: unknown): NormalizedApiError {
  if (isAxiosError(error)) {
    const axiosError = error as AxiosError<ApiErrorBody>;

    if (isCanceledError(axiosError)) {
      return {
        message: "Request was canceled.",
        statusCode: null,
        fieldErrors: [],
        code: axiosError.code ?? "ERR_CANCELED",
        kind: "canceled",
        isUnauthorized: false,
        isNetworkError: false,
        isTimeoutError: false,
        isCanceled: true,
      };
    }

    if (isTimeoutError(axiosError)) {
      return {
        message: "The request timed out. Please try again.",
        statusCode: null,
        fieldErrors: [],
        code: axiosError.code ?? "ETIMEDOUT",
        kind: "timeout",
        isUnauthorized: false,
        isNetworkError: false,
        isTimeoutError: true,
        isCanceled: false,
      };
    }

    if (isNetworkError(axiosError)) {
      return {
        message:
          "Unable to reach the server. Check your connection and try again.",
        statusCode: null,
        fieldErrors: [],
        code: axiosError.code ?? "ERR_NETWORK",
        kind: "network",
        isUnauthorized: false,
        isNetworkError: true,
        isTimeoutError: false,
        isCanceled: false,
      };
    }

    const body = asRecord(axiosError.response?.data) as ApiErrorBody | null;
    const fieldErrors = normalizeFieldErrors(body);
    const detailMessage =
      typeof body?.detail === "string" ? body.detail : undefined;
    const statusCode = axiosError.response?.status ?? null;

    return {
      message:
        body?.message ??
        detailMessage ??
        (statusCode === 401
          ? "Your session has expired. Please sign in again."
          : axiosError.message) ??
        "Something went wrong. Please try again.",
      statusCode,
      fieldErrors,
      code: body?.code ?? axiosError.code ?? null,
      kind: "http",
      isUnauthorized: statusCode === 401,
      isNetworkError: false,
      isTimeoutError: false,
      isCanceled: false,
    };
  }

  if (error instanceof Error) {
    return {
      message: error.message,
      statusCode: null,
      fieldErrors: [],
      code: null,
      kind: "unknown",
      isUnauthorized: false,
      isNetworkError: false,
      isTimeoutError: false,
      isCanceled: false,
    };
  }

  return {
    message: "Something went wrong. Please try again.",
    statusCode: null,
    fieldErrors: [],
    code: null,
    kind: "unknown",
    isUnauthorized: false,
    isNetworkError: false,
    isTimeoutError: false,
    isCanceled: false,
  };
}

export class ApiRequestError extends Error {
  readonly statusCode: number | null;
  readonly fieldErrors: ApiFieldError[];
  readonly code: string | null;
  readonly kind: ApiErrorKind;
  readonly isUnauthorized: boolean;
  readonly isNetworkError: boolean;
  readonly isTimeoutError: boolean;
  readonly isCanceled: boolean;
  readonly cause: unknown;

  constructor(normalized: NormalizedApiError, cause?: unknown) {
    super(normalized.message);
    this.name = "ApiRequestError";
    this.statusCode = normalized.statusCode;
    this.fieldErrors = normalized.fieldErrors;
    this.code = normalized.code;
    this.kind = normalized.kind;
    this.isUnauthorized = normalized.isUnauthorized;
    this.isNetworkError = normalized.isNetworkError;
    this.isTimeoutError = normalized.isTimeoutError;
    this.isCanceled = normalized.isCanceled;
    this.cause = cause;
  }
}

export function toApiRequestError(error: unknown): ApiRequestError {
  if (error instanceof ApiRequestError) {
    return error;
  }

  return new ApiRequestError(normalizeApiError(error), error);
}
