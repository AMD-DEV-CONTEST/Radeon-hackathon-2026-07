import { normalizeApiError } from "@/services/api/errors";

export function getPlanningErrorMessage(error: unknown): string {
  const normalized = normalizeApiError(error);

  if (normalized.isNetworkError) {
    return "Unable to reach the server. Check your connection and try again.";
  }

  return normalized.message || "Interview planning failed. Please retry.";
}

export function getCreateInterviewErrorMessage(error: unknown): string {
  const normalized = normalizeApiError(error);

  if (normalized.isNetworkError) {
    return "Unable to create the interview due to a network error.";
  }

  return (
    normalized.message || "Interview creation failed. Please try again."
  );
}

export function getCandidateMissingMessage(error: unknown): string {
  const normalized = normalizeApiError(error);

  if (normalized.statusCode === 404) {
    return "Candidate missing. Open a candidate dossier or upload a resume first.";
  }

  return getPlanningErrorMessage(error);
}

export function getResumeMissingMessage(error: unknown): string {
  const normalized = normalizeApiError(error);

  if (normalized.statusCode === 404) {
    return "Resume missing. Upload a resume before planning an interview.";
  }

  return getPlanningErrorMessage(error);
}

export function isNotFoundError(error: unknown): boolean {
  return normalizeApiError(error).statusCode === 404;
}
