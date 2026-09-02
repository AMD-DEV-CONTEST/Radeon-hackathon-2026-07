import { normalizeApiError } from "@/services/api/errors";

export function isNotFoundError(error: unknown): boolean {
  return normalizeApiError(error).statusCode === 404;
}

export function isReportNotReadyError(error: unknown): boolean {
  const normalized = normalizeApiError(error);
  const message = normalized.message.toLowerCase();

  if (normalized.statusCode === 404) {
    return (
      message.includes("not ready") ||
      message.includes("not generated") ||
      message.includes("pending") ||
      message.includes("generating")
    );
  }

  if (normalized.statusCode === 202 || normalized.statusCode === 409) {
    return true;
  }

  return (
    message.includes("not ready") ||
    message.includes("report is pending") ||
    message.includes("still generating")
  );
}

export function getReportErrorMessage(error: unknown): string {
  const normalized = normalizeApiError(error);

  if (normalized.statusCode === 404) {
    return "Report not found.";
  }

  if (isReportNotReadyError(error)) {
    return "The interview report is not ready yet. Generate it to continue.";
  }

  if (normalized.isNetworkError) {
    return "Unable to reach the server. Check your connection and try again.";
  }

  return normalized.message || "Unable to load the interview report.";
}

export function getGenerateReportErrorMessage(error: unknown): string {
  const normalized = normalizeApiError(error);

  if (normalized.isNetworkError) {
    return "Unable to generate the report due to a network error.";
  }

  if (normalized.statusCode === 404) {
    return "Interview not found. Unable to generate a report.";
  }

  return normalized.message || "Report generation failed. Please try again.";
}

export function getReportInterviewErrorMessage(error: unknown): string {
  const normalized = normalizeApiError(error);

  if (normalized.statusCode === 404) {
    return "Interview not found.";
  }

  if (normalized.isNetworkError) {
    return "Unable to reach the server. Check your connection and try again.";
  }

  return normalized.message || "Unable to load interview details.";
}
