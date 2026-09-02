"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  REPORT_MUTATION_KEYS,
  REPORT_QUERY_KEYS,
} from "@/features/report/constants/report-keys";
import { reportService } from "@/features/report/services/report.service";
import type { GenerateReportRequest } from "@/features/report/types/report.types";
import {
  getGenerateReportErrorMessage,
  getReportErrorMessage,
  getReportInterviewErrorMessage,
  isNotFoundError,
  isReportNotReadyError,
} from "@/features/report/utils/report-errors";

export const reportQueryKeys = REPORT_QUERY_KEYS;

export function useReport(reportId: string) {
  return useQuery({
    queryKey: REPORT_QUERY_KEYS.detail(reportId),
    queryFn: () => reportService.getReport(reportId),
    enabled: reportId.trim().length > 0,
    retry: 1,
    staleTime: 30_000,
  });
}

export function useReportInterview(interviewId: string | undefined) {
  return useQuery({
    queryKey: REPORT_QUERY_KEYS.interview(interviewId ?? "unknown"),
    queryFn: () => {
      if (!interviewId) {
        throw new Error("Interview id is required");
      }
      return reportService.getInterview(interviewId);
    },
    enabled: Boolean(interviewId && interviewId.trim().length > 0),
    retry: 1,
    staleTime: 30_000,
  });
}

export function useGenerateReport() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationKey: REPORT_MUTATION_KEYS.generate,
    retry: false,
    mutationFn: (payload: GenerateReportRequest) =>
      reportService.generateReport(payload),
    onSuccess: async (result) => {
      if (result.reportId) {
        await queryClient.invalidateQueries({
          queryKey: REPORT_QUERY_KEYS.detail(result.reportId),
        });
      }
      if (result.interviewId) {
        await queryClient.invalidateQueries({
          queryKey: REPORT_QUERY_KEYS.detail(result.interviewId),
        });
        await queryClient.invalidateQueries({
          queryKey: REPORT_QUERY_KEYS.interview(result.interviewId),
        });
      }
    },
  });
}

export {
  getGenerateReportErrorMessage,
  getReportErrorMessage,
  getReportInterviewErrorMessage,
  isNotFoundError,
  isReportNotReadyError,
};
