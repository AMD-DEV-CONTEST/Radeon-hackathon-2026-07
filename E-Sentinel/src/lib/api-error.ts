export function getPublicErrorMessage(error: unknown, fallback = "internal_error"): string {
  if (error instanceof Error && error.message) return error.message;
  if (!error || typeof error !== "object") return fallback;

  const err = error as {
    message?: unknown;
    code?: unknown;
    details?: unknown;
    hint?: unknown;
  };
  const parts = [err.message, err.details, err.hint]
    .filter((part): part is string => typeof part === "string" && part.trim().length > 0)
    .map((part) => part.trim());
  const message = parts.join(" ");
  if (message) return message;
  if (typeof err.code === "string" && err.code.trim()) return err.code.trim();
  return fallback;
}

/**
 * Accept either a date-only filter (which means the whole UTC day) or a full
 * ISO timestamp (which is already an exact upper bound).
 */
export function toUtcRangeEnd(value: string): string {
  return value.includes("T") ? value : `${value}T23:59:59.999Z`;
}
