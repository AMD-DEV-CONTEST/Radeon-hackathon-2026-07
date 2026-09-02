"use client";

import { create } from "zustand";

import type {
  InterviewQuestion,
  InterviewRoomPhase,
  InterviewRoomSession,
  LiveMetric,
  RoomAgent,
  TranscriptEntry,
} from "@/features/interview/types/interview.types";

interface InterviewRoomState {
  session: InterviewRoomSession | null;
  phase: InterviewRoomPhase;
  isSocketConnected: boolean;
  hydrateSession: (session: InterviewRoomSession) => void;
  setPhase: (phase: InterviewRoomPhase) => void;
  setSocketConnected: (connected: boolean) => void;
  toggleMute: () => void;
  toggleCamera: () => void;
  appendTranscript: (entry: TranscriptEntry) => void;
  setQuestion: (question: InterviewQuestion) => void;
  setProgress: (
    progressPercent: number,
    estimatedRemainingLabel?: string
  ) => void;
  setAgents: (agents: ReadonlyArray<RoomAgent>) => void;
  upsertAgent: (agent: Partial<RoomAgent> & { id: string }) => void;
  setMetrics: (metrics: ReadonlyArray<LiveMetric>) => void;
  setAiThinking: (isThinking: boolean) => void;
  setCandidateSpeaking: (isSpeaking: boolean) => void;
  setLatency: (latencyMs: number) => void;
  endSession: () => void;
  reset: () => void;
}

const initialState = {
  session: null,
  phase: "loading" as InterviewRoomPhase,
  isSocketConnected: false,
};

export const useInterviewStore = create<InterviewRoomState>((set) => ({
  ...initialState,
  hydrateSession: (session) => {
    set({
      session,
      phase: session.phase,
    });
  },
  setPhase: (phase) => {
    set((state) => ({
      phase,
      session: state.session
        ? {
            ...state.session,
            phase,
            status:
              phase === "ended"
                ? "ended"
                : phase === "cancelled"
                  ? "cancelled"
                  : state.session.status,
          }
        : null,
    }));
  },
  setSocketConnected: (connected) => {
    set({ isSocketConnected: connected });
  },
  toggleMute: () => {
    set((state) => {
      if (!state.session) {
        return state;
      }

      return {
        session: {
          ...state.session,
          isMuted: !state.session.isMuted,
        },
      };
    });
  },
  toggleCamera: () => {
    set((state) => {
      if (!state.session) {
        return state;
      }

      return {
        session: {
          ...state.session,
          isCameraOn: !state.session.isCameraOn,
        },
      };
    });
  },
  appendTranscript: (entry) => {
    set((state) => {
      if (!state.session) {
        return state;
      }

      const exists = state.session.transcript.some(
        (item) => item.id === entry.id
      );
      if (exists) {
        return state;
      }

      return {
        session: {
          ...state.session,
          transcript: [...state.session.transcript, entry],
        },
      };
    });
  },
  setQuestion: (question) => {
    set((state) => {
      if (!state.session) {
        return state;
      }

      return {
        session: {
          ...state.session,
          question,
          progressPercent:
            question.total > 0
              ? Math.round((question.index / question.total) * 100)
              : state.session.progressPercent,
        },
      };
    });
  },
  setProgress: (progressPercent, estimatedRemainingLabel) => {
    set((state) => {
      if (!state.session) {
        return state;
      }

      return {
        session: {
          ...state.session,
          progressPercent,
          estimatedRemainingLabel:
            estimatedRemainingLabel ?? state.session.estimatedRemainingLabel,
        },
      };
    });
  },
  setAgents: (agents) => {
    set((state) => {
      if (!state.session) {
        return state;
      }

      return {
        session: {
          ...state.session,
          agents,
        },
      };
    });
  },
  upsertAgent: (agent) => {
    set((state) => {
      if (!state.session) {
        return state;
      }

      const existingIndex = state.session.agents.findIndex(
        (item) => item.id === agent.id
      );
      const nextAgents = [...state.session.agents];

      if (existingIndex >= 0) {
        nextAgents[existingIndex] = {
          ...nextAgents[existingIndex],
          ...agent,
        } as RoomAgent;
      } else {
        nextAgents.push({
          id: agent.id,
          name: agent.name ?? agent.id,
          status: agent.status ?? "waiting",
          progress: agent.progress ?? 0,
          currentTask: agent.currentTask ?? "",
        });
      }

      return {
        session: {
          ...state.session,
          agents: nextAgents,
        },
      };
    });
  },
  setMetrics: (metrics) => {
    set((state) => {
      if (!state.session) {
        return state;
      }

      return {
        session: {
          ...state.session,
          metrics,
        },
      };
    });
  },
  setAiThinking: (isThinking) => {
    set((state) => {
      if (!state.session) {
        return state;
      }

      return {
        session: {
          ...state.session,
          isAiThinking: isThinking,
        },
      };
    });
  },
  setCandidateSpeaking: (isSpeaking) => {
    set((state) => {
      if (!state.session) {
        return state;
      }

      return {
        session: {
          ...state.session,
          isCandidateSpeaking: isSpeaking,
        },
      };
    });
  },
  setLatency: (latencyMs) => {
    set((state) => {
      if (!state.session) {
        return state;
      }

      return {
        session: {
          ...state.session,
          latencyMs,
        },
      };
    });
  },
  endSession: () => {
    set((state) => ({
      phase: "ended",
      session: state.session
        ? {
            ...state.session,
            status: "ended",
            phase: "ended",
            isCandidateSpeaking: false,
            isAiThinking: false,
          }
        : null,
    }));
  },
  reset: () => {
    set(initialState);
  },
}));
