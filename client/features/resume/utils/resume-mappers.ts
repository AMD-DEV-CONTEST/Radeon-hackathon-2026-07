import type {
  ResumeCandidateInfo,
  ResumeRecord,
  UploadResumeResponse,
} from "@/features/resume/types/resume.types";

/** Backend resume payload (snake_case). */
export interface BackendResumeDto {
  id: string;
  candidate_id: string;
  file_name: string;
  file_path: string;
  file_type: string | null;
  file_size: number | null;
  status: string;
  raw_text: string | null;
  parsed_data: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
  candidate?: {
    full_name?: string;
    email?: string;
    target_role?: string;
    years_of_experience?: number;
  } | null;
}

export interface BackendMessageDto {
  message: string;
}

const RESUME_FIELD_ALIASES: Record<string, string> = {
  full_name: "fullName",
  target_role: "targetRole",
  years_of_experience: "yearsOfExperience",
  file_name: "file",
  file_type: "file",
  file_size: "file",
};

export function mapResumeFieldName(field: string): string {
  return RESUME_FIELD_ALIASES[field] ?? field;
}

export function mapBackendResume(
  dto: BackendResumeDto,
  candidateFallback?: ResumeCandidateInfo
): ResumeRecord {
  const candidate: ResumeCandidateInfo = {
    fullName:
      dto.candidate?.full_name ?? candidateFallback?.fullName ?? "",
    email: dto.candidate?.email ?? candidateFallback?.email ?? "",
    targetRole:
      dto.candidate?.target_role ?? candidateFallback?.targetRole ?? "",
    yearsOfExperience:
      dto.candidate?.years_of_experience ??
      candidateFallback?.yearsOfExperience ??
      0,
  };

  return {
    id: String(dto.id),
    fileName: dto.file_name,
    fileSize: dto.file_size ?? 0,
    mimeType: dto.file_type ?? "application/octet-stream",
    status: dto.status,
    uploadedAt: dto.created_at,
    candidateId: String(dto.candidate_id),
    candidate,
  };
}

export function toUploadResumeResponse(
  record: ResumeRecord
): UploadResumeResponse {
  return {
    id: record.id,
    fileName: record.fileName,
    fileSize: record.fileSize,
    mimeType: record.mimeType,
    uploadedAt: record.uploadedAt,
    candidate: record.candidate,
  };
}
