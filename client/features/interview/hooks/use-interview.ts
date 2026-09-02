"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import {
  INTERVIEW_MUTATION_KEYS,
  INTERVIEW_QUERY_KEYS,
} from "@/features/interview/constants/interview-keys";
import { useInterviewSocket } from "@/features/interview/hooks/use-interview-socket";
import { interviewService } from "@/features/interview/services/interview.service";
import { useInterviewStore } from "@/features/interview/store/interview.store";
import {
  getEndInterviewErrorMessage,
  getInterviewRoomErrorMessage,
  getStartInterviewErrorMessage,
} from "@/features/interview/utils/room-errors";

export const interviewRoomQueryKeys = {
  all: INTERVIEW_QUERY_KEYS.all,
  detail: (id: string) => INTERVIEW_QUERY_KEYS.room(id),
  questions: (id: string) => INTERVIEW_QUERY_KEYS.questions(id),
  transcript: (id: string) => INTERVIEW_QUERY_KEYS.transcript(id),
};

export function useInterview(interviewId: string) {
  const queryClient = useQueryClient();
  const hasAutoStartedRef = useRef(false);

  const hydrateSession = useInterviewStore((state) => state.hydrateSession);
  const endSession = useInterviewStore((state) => state.endSession);
  const setPhase = useInterviewStore((state) => state.setPhase);
  const reset = useInterviewStore((state) => state.reset);
  const session = useInterviewStore((state) => state.session);
  const phase = useInterviewStore((state) => state.phase);
  const toggleMute = useInterviewStore((state) => state.toggleMute);
  const toggleCamera = useInterviewStore((state) => state.toggleCamera);

  const enabled = interviewId.trim().length > 0;

  const sessionQuery = useQuery({
    queryKey: INTERVIEW_QUERY_KEYS.room(interviewId),
    queryFn: () => interviewService.getInterviewRoom(interviewId),
    enabled,
    staleTime: 10_000,
    retry: 1,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "live" ? 15_000 : false;
    },
  });

  const questionsQuery = useQuery({
    queryKey: INTERVIEW_QUERY_KEYS.questions(interviewId),
    queryFn: () => interviewService.getQuestions(interviewId),
    enabled: enabled && Boolean(sessionQuery.data),
    staleTime: 8_000,
    retry: 1,
  });

  const transcriptQuery = useQuery({
    queryKey: INTERVIEW_QUERY_KEYS.transcript(interviewId),
    queryFn: () => interviewService.getTranscript(interviewId),
    enabled: enabled && Boolean(sessionQuery.data),
    staleTime: 5_000,
    retry: 1,
    refetchInterval: sessionQuery.data?.status === "live" ? 8_000 : false,
  });

  useEffect(() => {
    if (!sessionQuery.data) {
      return;
    }

    const nextSession = {
      ...sessionQuery.data,
      question:
        questionsQuery.data?.currentQuestion ?? sessionQuery.data.question,
      transcript: transcriptQuery.data ?? sessionQuery.data.transcript,
      progressPercent:
        questionsQuery.data?.currentQuestion &&
        questionsQuery.data.currentQuestion.total > 0
          ? Math.round(
              (questionsQuery.data.currentQuestion.index /
                questionsQuery.data.currentQuestion.total) *
                100
            )
          : sessionQuery.data.progressPercent,
    };

    hydrateSession(nextSession);
  }, [
    hydrateSession,
    sessionQuery.data,
    questionsQuery.data,
    transcriptQuery.data,
  ]);

  useEffect(() => {
    return () => {
      reset();
      hasAutoStartedRef.current = false;
    };
  }, [reset, interviewId]);

  const liveInterviewId =
    sessionQuery.data?.status === "live" || session?.status === "live"
      ? interviewId
      : undefined;

  const socket = useInterviewSocket(liveInterviewId);

  const startMutation = useMutation({
    mutationKey: [...INTERVIEW_MUTATION_KEYS.start, interviewId],
    retry: false,
    mutationFn: () =>
      interviewService.startInterview({
        interviewId,
      }),
    onSuccess: async (result) => {
      hydrateSession(result.session);
      await queryClient.invalidateQueries({
        queryKey: INTERVIEW_QUERY_KEYS.room(interviewId),
      });
      await queryClient.invalidateQueries({
        queryKey: INTERVIEW_QUERY_KEYS.questions(interviewId),
      });
    },
  });

  const endMutation = useMutation({
    mutationKey: [...INTERVIEW_MUTATION_KEYS.end, interviewId],
    retry: false,
    mutationFn: () =>
      interviewService.endInterview({
        interviewId,
        reason: "manual",
      }),
    onSuccess: async () => {
      endSession();
      await queryClient.invalidateQueries({
        queryKey: INTERVIEW_QUERY_KEYS.room(interviewId),
      });
    },
  });

  const startInterview = startMutation.mutateAsync;
  const isStarting = startMutation.isPending;

  useEffect(() => {
    if (hasAutoStartedRef.current || isStarting) {
      return;
    }

    if (sessionQuery.data?.status !== "scheduled") {
      return;
    }

    hasAutoStartedRef.current = true;
    void startInterview();
  }, [sessionQuery.data?.status, isStarting, startInterview]);

  return {
    interviewId,
    session,
    phase,
    socket,
    sessionQuery,
    questionsQuery,
    transcriptQuery,
    startMutation,
    endMutation,
    toggleMute,
    toggleCamera,
    setPhase,
    isLoading: sessionQuery.isLoading,
    isError: sessionQuery.isError,
    error: sessionQuery.error,
    refetch: async () => {
      await Promise.all([
        sessionQuery.refetch(),
        questionsQuery.refetch(),
        transcriptQuery.refetch(),
      ]);
    },
    getRoomErrorMessage: getInterviewRoomErrorMessage,
    getStartErrorMessage: getStartInterviewErrorMessage,
    getEndErrorMessage: getEndInterviewErrorMessage,
  };
}
