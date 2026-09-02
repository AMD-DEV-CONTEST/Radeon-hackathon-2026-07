import { normalizeApiError } from "@/services/api/errors";

export function getCandidateErrorMessage(error: unknown): string {
  const normalized = normalizeApiError(error);

  if (normalized.statusCode === 404) {
    if (/resume/i.test(normalized.message)) {
      return "Resume not found for this candidate.";
    }
    return "Candidate not found.";
  }

  if (normalized.isNetworkError) {
    return "Unable to reach the server. Check your connection and try again.";
  }

  return normalized.message || "Unexpected server error. Please try again.";
}

export function getResumeMissingMessage(error: unknown): string {
  const normalized = normalizeApiError(error);

  if (normalized.statusCode === 404) {
    return "Resume is missing for this candidate. Upload a resume to continue.";
  }

  return getCandidateErrorMessage(error);
}

export function getAnalyzeResumeErrorMessage(error: unknown): string {
  const normalized = normalizeApiError(error);

  if (normalized.statusCode === 404) {
    return "Resume not found. Upload a resume before running AI analysis.";
  }

  if (normalized.isNetworkError) {
    return "Analysis failed due to a network error. Please retry.";
  }

  return (
    normalized.message || "Resume analysis failed. Please try again."
  );
}

export function isNotFoundError(error: unknown): boolean {
  return normalizeApiError(error).statusCode === 404;
}
