export type KnownRuntimeApiErrorCode =
  | "EVENT_NOT_FOUND"
  | "TASK_NOT_FOUND"
  | "INVALID_REQUEST"
  | "HUMAN_REVIEW_REQUIRED"
  | "PROVIDER_UNAVAILABLE"
  | "ANALYSIS_NOT_AVAILABLE"
  | "ANALYSIS_FAILED"
  | "INTERNAL_ERROR";

export type RuntimeApiErrorCode =
  | KnownRuntimeApiErrorCode
  | "UNKNOWN_API_ERROR"
  | "INVALID_RESPONSE"
  | "NETWORK_ERROR"
  | "ABORTED";

export class RuntimeApiError extends Error {
  readonly code: RuntimeApiErrorCode;
  readonly rawCode: string | null;
  readonly status: number | null;

  constructor({
    code,
    message,
    rawCode = null,
    status = null,
    cause,
  }: {
    code: RuntimeApiErrorCode;
    message: string;
    rawCode?: string | null;
    status?: number | null;
    cause?: unknown;
  }) {
    super(message, { cause });
    this.name = "RuntimeApiError";
    this.code = code;
    this.rawCode = rawCode;
    this.status = status;
  }
}

const knownCodes = new Set<KnownRuntimeApiErrorCode>([
  "EVENT_NOT_FOUND",
  "TASK_NOT_FOUND",
  "INVALID_REQUEST",
  "HUMAN_REVIEW_REQUIRED",
  "PROVIDER_UNAVAILABLE",
  "ANALYSIS_NOT_AVAILABLE",
  "ANALYSIS_FAILED",
  "INTERNAL_ERROR",
]);

export function normalizeRuntimeApiErrorCode(
  rawCode: string,
): RuntimeApiErrorCode {
  return knownCodes.has(rawCode as KnownRuntimeApiErrorCode)
    ? (rawCode as KnownRuntimeApiErrorCode)
    : "UNKNOWN_API_ERROR";
}
