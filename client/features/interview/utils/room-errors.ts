import { normalizeApiError } from "@/services/api/errors";

export function getInterviewRoomErrorMessage(error: unknown): string {
  const normalized = normalizeApiError(error);

  if (normalized.statusCode === 404) {
    return "Interview not found.";
  }

  if (normalized.isNetworkError) {
    return "Unable to reach the server. Check your connection and try again.";
  }

  return normalized.message || "Unable to load the interview room.";
}

export function getStartInterviewErrorMessage(error: unknown): string {
  const normalized = normalizeApiError(error);

  if (normalized.isNetworkError) {
    return "Unable to start the interview due to a network error.";
  }

  return normalized.message || "Unable to start the interview.";
}

export function getEndInterviewErrorMessage(error: unknown): string {
  const normalized = normalizeApiError(error);

  if (normalized.isNetworkError) {
    return "Unable to end the interview due to a network error.";
  }

  return normalized.message || "Unable to end the interview.";
}

export function isNotFoundError(error: unknown): boolean {
  return normalizeApiError(error).statusCode === 404;
}
