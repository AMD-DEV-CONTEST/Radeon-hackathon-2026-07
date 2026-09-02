import { normalizeApiError } from "@/services/api/errors";

export function isNotFoundError(error: unknown): boolean {
  return normalizeApiError(error).statusCode === 404;
}

export function getPresentationErrorMessage(error: unknown): string {
  const normalized = normalizeApiError(error);

  if (normalized.statusCode === 404) {
    return "Presentation not found for this candidate.";
  }

  if (normalized.isNetworkError) {
    return "Unable to reach the server. Check your connection and try again.";
  }

  return normalized.message || "Unable to load the presentation dashboard.";
}

export function getPresentationReportErrorMessage(error: unknown): string {
  const normalized = normalizeApiError(error);

  if (normalized.statusCode === 404) {
    return "Report not found.";
  }

  if (normalized.isNetworkError) {
    return "Unable to reach the server. Check your connection and try again.";
  }

  return normalized.message || "Unable to load the presentation report.";
}

export function getPresentationCandidateErrorMessage(error: unknown): string {
  const normalized = normalizeApiError(error);

  if (normalized.statusCode === 404) {
    return "Candidate not found.";
  }

  if (normalized.isNetworkError) {
    return "Unable to reach the server. Check your connection and try again.";
  }

  return normalized.message || "Unable to load candidate details.";
}
