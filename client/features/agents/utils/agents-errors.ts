import { normalizeApiError } from "@/services/api/errors";

export function isNotFoundError(error: unknown): boolean {
  return normalizeApiError(error).statusCode === 404;
}

export function getAgentsErrorMessage(error: unknown): string {
  const normalized = normalizeApiError(error);

  if (normalized.statusCode === 404) {
    return "Agent monitoring data was not found.";
  }

  if (normalized.isNetworkError) {
    return "Unable to reach the server. Check your connection and try again.";
  }

  return normalized.message || "Unable to load agent monitoring.";
}

export function getAgentsStatusErrorMessage(error: unknown): string {
  const normalized = normalizeApiError(error);

  if (normalized.isNetworkError) {
    return "Unable to load agent status due to a network error.";
  }

  return normalized.message || "Unable to load agent status.";
}

export function getAgentsLogsErrorMessage(error: unknown): string {
  const normalized = normalizeApiError(error);

  if (normalized.isNetworkError) {
    return "Unable to load agent logs due to a network error.";
  }

  return normalized.message || "Unable to load agent logs.";
}

export function getAgentsMetricsErrorMessage(error: unknown): string {
  const normalized = normalizeApiError(error);

  if (normalized.isNetworkError) {
    return "Unable to load agent metrics due to a network error.";
  }

  return normalized.message || "Unable to load agent metrics.";
}
