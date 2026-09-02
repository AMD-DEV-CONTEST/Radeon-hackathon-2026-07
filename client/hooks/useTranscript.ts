"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo } from "react";

import { INTERVIEW_QUERY_KEYS } from "@/features/interview/constants/interview-keys";
import { interviewService } from "@/features/interview/services/interview.service";
import { useInterviewStore } from "@/features/interview/store/interview.store";
import type { TranscriptEntry } from "@/features/interview/types/interview.types";
import { transcriptSocket } from "@/services/websocket/transcript.socket";

export function useTranscript(interviewId?: string) {
  const storeTranscript = useInterviewStore(
    (state) => state.session?.transcript ?? []
  );
  const appendTranscript = useInterviewStore((state) => state.appendTranscript);
  const setAiThinking = useInterviewStore((state) => state.setAiThinking);
  const setCandidateSpeaking = useInterviewStore(
    (state) => state.setCandidateSpeaking
  );
  const sessionId = useInterviewStore((state) => state.session?.id ?? "");

  const resolvedInterviewId = interviewId || sessionId;

  const transcriptQuery = useQuery({
    queryKey: INTERVIEW_QUERY_KEYS.transcript(resolvedInterviewId || "unknown"),
    queryFn: () => interviewService.getTranscript(resolvedInterviewId),
    enabled: resolvedInterviewId.length > 0,
    staleTime: 5_000,
    retry: 1,
  });

  useEffect(() => {
    if (!resolvedInterviewId) {
      return;
    }

    transcriptSocket.subscribe(resolvedInterviewId);

    const unsubscribeTranscript = transcriptSocket.onTranscriptUpdated(
      (payload) => {
        if (payload.interviewId !== resolvedInterviewId) {
          return;
        }
        appendTranscript(payload.entry);
      }
    );

    const unsubscribeThinking = transcriptSocket.onAiThinking((payload) => {
      if (payload.interviewId !== resolvedInterviewId) {
        return;
      }
      setAiThinking(payload.isThinking);
    });

    const unsubscribeSpeaking = transcriptSocket.onCandidateSpeaking(
      (payload) => {
        if (payload.interviewId && payload.interviewId !== resolvedInterviewId) {
          return;
        }
        setCandidateSpeaking(payload.isSpeaking);
      }
    );

    const unsubscribeResponse = transcriptSocket.onAiResponse((payload) => {
      if (payload.interviewId !== resolvedInterviewId) {
        return;
      }
      appendTranscript({
        id: `ai-response-${payload.at}`,
        speaker: "ai",
        speakerLabel: "AI AGENT",
        timestamp: payload.at,
        content: payload.content,
      });
    });

    return () => {
      unsubscribeTranscript();
      unsubscribeThinking();
      unsubscribeSpeaking();
      unsubscribeResponse();
      transcriptSocket.unsubscribe();
    };
  }, [
    appendTranscript,
    resolvedInterviewId,
    setAiThinking,
    setCandidateSpeaking,
  ]);

  const transcript = useMemo(() => {
    if (!transcriptQuery.data || transcriptQuery.data.length === 0) {
      return storeTranscript;
    }

    if (storeTranscript.length === 0) {
      return transcriptQuery.data;
    }

    const byId = new Map<string, TranscriptEntry>();
    for (const entry of transcriptQuery.data) {
      byId.set(entry.id, entry);
    }
    for (const entry of storeTranscript) {
      byId.set(entry.id, entry);
    }
    return Array.from(byId.values());
  }, [storeTranscript, transcriptQuery.data]);

  const latestEntry = useMemo<TranscriptEntry | null>(() => {
    if (transcript.length === 0) {
      return null;
    }
    return transcript[transcript.length - 1] ?? null;
  }, [transcript]);

  return {
    transcript,
    latestEntry,
    appendTranscript,
    transcriptQuery,
  };
}
