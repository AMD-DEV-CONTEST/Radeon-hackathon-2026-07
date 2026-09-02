export const RESUME_ACCEPTED_MIME_TYPES = [
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
] as const;

export const RESUME_ACCEPTED_EXTENSIONS = [".pdf", ".docx"] as const;

export const RESUME_MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024;

export type ResumeAcceptedMimeType =
  (typeof RESUME_ACCEPTED_MIME_TYPES)[number];

export interface ResumeCandidateInfo {
  fullName: string;
  email: string;
  targetRole: string;
  yearsOfExperience: number;
}

export interface UploadResumePayload extends ResumeCandidateInfo {
  file: File;
}

export interface ResumeRecord {
  id: string;
  fileName: string;
  fileSize: number;
  mimeType: string;
  status: string;
  uploadedAt: string;
  candidateId: string;
  candidate: ResumeCandidateInfo;
}

export interface UploadResumeResponse {
  id: string;
  fileName: string;
  fileSize: number;
  mimeType: string;
  uploadedAt: string;
  candidate: ResumeCandidateInfo;
}

export interface DeleteResumeResponse {
  message: string;
}

export type UploadStatus = "idle" | "uploading" | "success" | "error";

export interface UploadProgressState {
  status: UploadStatus;
  progress: number;
  errorMessage: string | null;
}
