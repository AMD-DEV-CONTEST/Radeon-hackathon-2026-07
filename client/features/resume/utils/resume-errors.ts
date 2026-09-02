import { mapResumeFieldName } from "@/features/resume/utils/resume-mappers";
import { normalizeApiError } from "@/services/api/errors";

export function getResumeErrorMessage(error: unknown): string {
  const normalized = normalizeApiError(error);

  if (normalized.statusCode === 413) {
    return "The resume is too large. Maximum size is 10MB.";
  }

  if (normalized.statusCode === 415) {
    return "Unsupported file type. Please upload a PDF or DOCX resume.";
  }

  if (
    normalized.statusCode === 409 ||
    /duplicate|already uploaded|already exists/i.test(normalized.message)
  ) {
    return "This resume was already uploaded. Remove it or replace the file.";
  }

  if (
    /unsupported|invalid file|only pdf|docx|file type/i.test(normalized.message)
  ) {
    return normalized.message;
  }

  if (normalized.isNetworkError) {
    return "Unable to reach the server. Check your connection and try again.";
  }

  return normalized.message || "Unexpected server error. Please try again.";
}

export function getResumeFieldErrors(error: unknown): Record<string, string> {
  const normalized = normalizeApiError(error);

  return normalized.fieldErrors.reduce<Record<string, string>>(
    (accumulator, fieldError) => {
      const field = mapResumeFieldName(fieldError.field);
      if (!accumulator[field]) {
        accumulator[field] = fieldError.message;
      }
      return accumulator;
    },
    {}
  );
}
