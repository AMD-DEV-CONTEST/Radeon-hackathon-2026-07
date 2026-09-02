"use client";

import { api } from "@/services/api/client";
import type {
  DeleteResumeResponse,
  ResumeCandidateInfo,
  ResumeRecord,
  UploadResumePayload,
  UploadResumeResponse,
} from "@/features/resume/types/resume.types";
import {
  mapBackendResume,
  toUploadResumeResponse,
  type BackendMessageDto,
  type BackendResumeDto,
} from "@/features/resume/utils/resume-mappers";

export interface UploadResumeOptions {
  onProgress?: (progress: number) => void;
  signal?: AbortSignal;
}

export const resumeService = {
  async uploadResume(
    payload: UploadResumePayload,
    options: UploadResumeOptions = {}
  ): Promise<UploadResumeResponse> {
    const candidate: ResumeCandidateInfo = {
      fullName: payload.fullName,
      email: payload.email,
      targetRole: payload.targetRole,
      yearsOfExperience: payload.yearsOfExperience,
    };

    const data = await api.upload<BackendResumeDto>(
      "/resume/upload",
      payload.file,
      {
        fileField: "file",
        fields: {
          full_name: payload.fullName,
          email: payload.email,
          target_role: payload.targetRole,
          years_of_experience: String(payload.yearsOfExperience),
        },
        signal: options.signal,
        onUploadProgress: options.onProgress,
      }
    );

    return toUploadResumeResponse(mapBackendResume(data, candidate));
  },

  async getResume(resumeId: string): Promise<ResumeRecord> {
    const data = await api.get<BackendResumeDto>(`/resume/${resumeId}`);
    return mapBackendResume(data);
  },

  async deleteResume(resumeId: string): Promise<DeleteResumeResponse> {
    const data = await api.delete<BackendMessageDto>(`/resume/${resumeId}`);
    return { message: data.message };
  },
};
