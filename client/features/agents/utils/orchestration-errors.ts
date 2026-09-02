import { normalizeApiError } from "@/services/api/errors";

export function getOrchestrationErrorMessage(error: unknown): string {
  const normalized = normalizeApiError(error);

  if (normalized.isNetworkError) {
    return "Unable to reach orchestration services. Check your connection and retry.";
  }

  if (normalized.statusCode === 404) {
    return "Required orchestration resource was not found.";
  }

  return normalized.message || "Agent orchestration failed.";
}

export function getAgentFailedMessage(agentName: string, error: unknown): string {
  const detail = getOrchestrationErrorMessage(error);
  return `${agentName} failed: ${detail}`;
}

export function isRetryableOrchestrationError(error: unknown): boolean {
  const normalized = normalizeApiError(error);
  if (normalized.isNetworkError || normalized.isTimeoutError) {
    return true;
  }
  if (normalized.statusCode === null) {
    return true;
  }
  return normalized.statusCode >= 500 || normalized.statusCode === 429;
}
