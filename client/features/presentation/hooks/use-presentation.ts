"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo } from "react";

import { PRESENTATION_QUERY_KEYS } from "@/features/presentation/constants/presentation-keys";
import { presentationService } from "@/features/presentation/services/presentation.service";
import {
  getPresentationCandidateErrorMessage,
  getPresentationErrorMessage,
  getPresentationReportErrorMessage,
  isNotFoundError,
} from "@/features/presentation/utils/presentation-errors";
import { mergePresentationDashboard } from "@/features/presentation/utils/presentation-mappers";
import { useSocket } from "@/hooks/useSocket";
import { SOCKET_EVENTS } from "@/services/websocket/events";
import { socketManager } from "@/services/websocket/socket";

export const presentationQueryKeys = PRESENTATION_QUERY_KEYS;

export function usePresentation(candidateId: string) {
  return useQuery({
    queryKey: PRESENTATION_QUERY_KEYS.detail(candidateId),
    queryFn: () => presentationService.getPresentation(candidateId),
    enabled: candidateId.trim().length > 0,
    retry: 1,
    staleTime: 30_000,
  });
}

export function usePresentationReport(reportId: string | undefined) {
  return useQuery({
    queryKey: PRESENTATION_QUERY_KEYS.report(reportId ?? "unknown"),
    queryFn: () => {
      if (!reportId) {
        throw new Error("Report id is required");
      }
      return presentationService.getReport(reportId);
    },
    enabled: Boolean(reportId && reportId.trim().length > 0),
    retry: 1,
    staleTime: 30_000,
  });
}

export function usePresentationCandidate(candidateId: string | undefined) {
  return useQuery({
    queryKey: PRESENTATION_QUERY_KEYS.candidate(candidateId ?? "unknown"),
    queryFn: () => {
      if (!candidateId) {
        throw new Error("Candidate id is required");
      }
      return presentationService.getCandidate(candidateId);
    },
    enabled: Boolean(candidateId && candidateId.trim().length > 0),
    retry: 1,
    staleTime: 30_000,
  });
}

export function usePresentationDashboard(candidateId: string) {
  const presentationQuery = usePresentation(candidateId);
  const reportQuery = usePresentationReport(presentationQuery.data?.reportId);
  const candidateQuery = usePresentationCandidate(
    candidateId || presentationQuery.data?.candidate.id
  );
  const socket = useSocket({ enabled: candidateId.trim().length > 0 });

  const data = useMemo(() => {
    if (!presentationQuery.data) {
      return undefined;
    }

    return mergePresentationDashboard({
      presentation: presentationQuery.data,
      report: reportQuery.data ?? null,
      candidate: candidateQuery.data ?? null,
    });
  }, [presentationQuery.data, reportQuery.data, candidateQuery.data]);

  useEffect(() => {
    if (!candidateId.trim()) {
      return;
    }

    const refetchPresentation = () => {
      void presentationQuery.refetch();
    };
    const refetchReport = () => {
      void reportQuery.refetch();
    };

    const unsubscribers = [
      socketManager.on(SOCKET_EVENTS.evaluationUpdated, () => {
        refetchPresentation();
        refetchReport();
      }),
      socketManager.on(SOCKET_EVENTS.interviewEnded, () => {
        refetchPresentation();
        refetchReport();
      }),
      socketManager.on(SOCKET_EVENTS.progressUpdated, () => {
        refetchPresentation();
      }),
      socketManager.on(SOCKET_EVENTS.reconnect, () => {
        refetchPresentation();
        refetchReport();
      }),
    ];

    return () => {
      for (const unsubscribe of unsubscribers) {
        unsubscribe();
      }
    };
  }, [candidateId, presentationQuery.refetch, reportQuery.refetch]);

  return {
    data,
    presentationQuery,
    reportQuery,
    candidateQuery,
    socket,
    isLoading: presentationQuery.isLoading,
    isFetching:
      presentationQuery.isFetching ||
      reportQuery.isFetching ||
      candidateQuery.isFetching,
    isError: presentationQuery.isError,
    error: presentationQuery.error,
    refetch: async () => {
      await Promise.all([
        presentationQuery.refetch(),
        reportQuery.refetch(),
        candidateQuery.refetch(),
      ]);
    },
  };
}

export {
  getPresentationCandidateErrorMessage,
  getPresentationErrorMessage,
  getPresentationReportErrorMessage,
  isNotFoundError,
};
