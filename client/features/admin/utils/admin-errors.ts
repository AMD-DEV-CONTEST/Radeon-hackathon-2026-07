import { normalizeApiError } from "@/services/api/errors";

export function isNotFoundError(error: unknown): boolean {
  return normalizeApiError(error).statusCode === 404;
}

export function getAdminDashboardErrorMessage(error: unknown): string {
  const normalized = normalizeApiError(error);

  if (normalized.statusCode === 404) {
    return "Admin dashboard was not found.";
  }

  if (normalized.isNetworkError) {
    return "Unable to reach the server. Check your connection and try again.";
  }

  return normalized.message || "Unable to load the admin dashboard.";
}

export function getAdminAnalyticsErrorMessage(error: unknown): string {
  const normalized = normalizeApiError(error);

  if (normalized.isNetworkError) {
    return "Unable to load analytics due to a network error.";
  }

  return normalized.message || "Unable to load admin analytics.";
}

export function getAdminUsersErrorMessage(error: unknown): string {
  const normalized = normalizeApiError(error);

  if (normalized.isNetworkError) {
    return "Unable to load users due to a network error.";
  }

  return normalized.message || "Unable to load admin users.";
}

export function getAdminInterviewsErrorMessage(error: unknown): string {
  const normalized = normalizeApiError(error);

  if (normalized.isNetworkError) {
    return "Unable to load interviews due to a network error.";
  }

  return normalized.message || "Unable to load admin interviews.";
}

export function getAdminSystemErrorMessage(error: unknown): string {
  const normalized = normalizeApiError(error);

  if (normalized.isNetworkError) {
    return "Unable to load system health due to a network error.";
  }

  return normalized.message || "Unable to load system health.";
}
