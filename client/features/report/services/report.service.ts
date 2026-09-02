"use client";

import type {
  GenerateReportRequest,
  GenerateReportResponse,
  InterviewLookup,
  InterviewReport,
} from "@/features/report/types/report.types";
import {
  mapGenerateReportResponse,
  mapInterviewLookup,
  mapInterviewReport,
} from "@/features/report/utils/report-mappers";
import { api } from "@/services/api/client";

export const reportService = {
  async getReport(id: string): Promise<InterviewReport> {
    const data = await api.get<unknown>(`/report/${id}`);
    return mapInterviewReport(data);
  },

  async generateReport(
    payload: GenerateReportRequest
  ): Promise<GenerateReportResponse> {
    const data = await api.post<unknown>("/report/generate", {
      interview_id: payload.interviewId,
    });
    return mapGenerateReportResponse(data);
  },

  async getInterview(id: string): Promise<InterviewLookup> {
    const data = await api.get<unknown>(`/interview/${id}`);
    return mapInterviewLookup(data);
  },
};
