import type { InterviewConfiguration } from "@/features/interview/types/interview.types";

export const INTERVIEW_QUERY_KEYS = {
  all: ["interview"] as const,
  candidate: (candidateId: string) =>
    [...INTERVIEW_QUERY_KEYS.all, "candidate", candidateId] as const,
  resume: (resumeId: string) =>
    [...INTERVIEW_QUERY_KEYS.all, "resume", resumeId] as const,
  plan: (candidateId: string, resumeId: string) =>
    [...INTERVIEW_QUERY_KEYS.all, "plan", candidateId, resumeId] as const,
  room: (interviewId: string) =>
    [...INTERVIEW_QUERY_KEYS.all, "room", interviewId] as const,
  questions: (interviewId: string) =>
    [...INTERVIEW_QUERY_KEYS.all, "questions", interviewId] as const,
  transcript: (interviewId: string) =>
    [...INTERVIEW_QUERY_KEYS.all, "transcript", interviewId] as const,
} as const;

export const INTERVIEW_MUTATION_KEYS = {
  plan: ["interview", "plan"] as const,
  create: ["interview", "create"] as const,
  start: ["interview", "start"] as const,
  end: ["interview", "end"] as const,
} as const;

/** Initial form defaults for interview configuration controls. */
export const DEFAULT_INTERVIEW_CONFIGURATION: InterviewConfiguration = {
  role: "",
  difficulty: "medium",
  durationMinutes: 60,
  questionCount: 12,
  interviewType: "mixed",
};
