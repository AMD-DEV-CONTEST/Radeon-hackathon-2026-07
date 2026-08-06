export type ToolSuccess<T> = {
  ok: true;
  tool: string;
  data: T;
  dataVersion?: number;
  auditRef: string;
};

export type ToolFailure = {
  ok: false;
  tool: string;
  code:
    | "VALIDATION_ERROR"
    | "NOT_FOUND"
    | "STALE_CONTEXT"
    | "GUARD_CONFIG_MISSING"
    | "RISK_GUARD_TRIGGERED"
    | "TIMEOUT"
    | "INTERNAL_ERROR"
    | "NO_FEASIBLE_PLAN";
  userSafeMessage: string;
  retryable: boolean;
  auditRef: string;
};

export type ToolResult<T> = ToolSuccess<T> | ToolFailure;

export function toolSuccess<T>(
  tool: string,
  data: T,
  auditRef: string,
  dataVersion?: number
): ToolSuccess<T> {
  return dataVersion == null
    ? { ok: true, tool, data, auditRef }
    : { ok: true, tool, data, auditRef, dataVersion };
}

export function toolFailure(
  tool: string,
  code: ToolFailure["code"],
  userSafeMessage: string,
  auditRef: string,
  retryable = false
): ToolFailure {
  return { ok: false, tool, code, userSafeMessage, retryable, auditRef };
}
