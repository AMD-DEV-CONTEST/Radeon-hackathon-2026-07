"use client";

import type {
  AnalyzeResumeRequest,
  AnalyzeResumeResponse,
  CandidateDossier,
  ResumeDetails,
  UpdateCandidateRequest,
} from "@/features/candidate/types/candidate.types";
import {
  mapAnalyzeResumeResponse,
  mapCandidateDossier,
  mapResumeDetails,
  toBackendCandidateUpdate,
  type BackendAnalysisDto,
  type BackendCandidateDto,
} from "@/features/candidate/utils/candidate-mappers";
import { api } from "@/services/api/client";
import type { BackendResumeDto } from "@/features/resume/utils/resume-mappers";
import { mapBackendResume } from "@/features/resume/utils/resume-mappers";

export const candidateService = {
  async getCandidate(id: string): Promise<CandidateDossier> {
    const data = await api.get<BackendCandidateDto>(`/candidate/${id}`);
    return mapCandidateDossier(data, {
      resumeId: data.resume_id ? String(data.resume_id) : null,
    });
  },

  async updateCandidate(
    id: string,
    payload: UpdateCandidateRequest
  ): Promise<CandidateDossier> {
    const data = await api.put<BackendCandidateDto>(
      `/candidate/${id}`,
      toBackendCandidateUpdate(payload)
    );
    return mapCandidateDossier(data, {
      resumeId: data.resume_id ? String(data.resume_id) : null,
    });
  },

  async getResume(id: string): Promise<ResumeDetails> {
    const data = await api.get<BackendResumeDto>(`/resume/${id}`);
    const record = mapBackendResume(data);
    return mapResumeDetails(record, data);
  },

  async analyzeResume(
    payload: AnalyzeResumeRequest
  ): Promise<AnalyzeResumeResponse> {
    const data = await api.post<BackendAnalysisDto>("/resume/analyze", {
      resume_id: payload.resumeId,
    });
    return mapAnalyzeResumeResponse(data);
  },
};
