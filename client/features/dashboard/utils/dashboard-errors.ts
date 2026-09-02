import { normalizeApiError } from "@/services/api/errors";

export function getDashboardErrorMessage(error: unknown): string {
  const normalized = normalizeApiError(error);

  if (normalized.isNetworkError) {
    return "Unable to reach the server. Check your connection and try again.";
  }

  if (normalized.statusCode === 404) {
    return "Dashboard unavailable. Complete onboarding to populate your workspace.";
  }

  return normalized.message || "Dashboard unavailable. Please try again.";
}

export function getDashboardInterviewsErrorMessage(error: unknown): string {
  const normalized = normalizeApiError(error);

  if (normalized.statusCode === 404) {
    return "No interviews found.";
  }

  if (normalized.isNetworkError) {
    return "Unable to load interviews due to a network error.";
  }

  return normalized.message || "Unable to load interviews.";
}

export function getDashboardReportsErrorMessage(error: unknown): string {
  const normalized = normalizeApiError(error);

  if (normalized.statusCode === 404) {
    return "No reports available.";
  }

  if (normalized.isNetworkError) {
    return "Unable to load reports due to a network error.";
  }

  return normalized.message || "Unable to load reports.";
}
