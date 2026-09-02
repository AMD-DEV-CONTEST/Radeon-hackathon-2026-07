"use client";

import { candidateService } from "@/features/candidate/services/candidate.service";
import type {
  CandidateDossier,
  ResumeDetails,
} from "@/features/candidate/types/candidate.types";
import type {
  CreateInterviewRequest,
  CreateInterviewResponse,
  EndInterviewRequest,
  EndInterviewResponse,
  InterviewPlan,
  InterviewQuestion,
  InterviewRoomSession,
  PlanInterviewRequest,
  PlanInterviewResponse,
  StartInterviewRequest,
  StartInterviewResponse,
  TranscriptEntry,
} from "@/features/interview/types/interview.types";
import {
  mapCreateInterviewResponse,
  mapInterviewPlan,
  mapPlanningCandidate,
} from "@/features/interview/utils/planning-mappers";
import {
  mapEndInterviewResponse,
  mapInterviewRoomSession,
  mapQuestionsPayload,
  mapStartInterviewResponse,
  mapTranscriptPayload,
  mergeRoomSession,
} from "@/features/interview/utils/room-mappers";
import { api } from "@/services/api/client";

export const interviewService = {
  async getCandidate(id: string): Promise<CandidateDossier> {
    return candidateService.getCandidate(id);
  },

  async getResume(id: string): Promise<ResumeDetails> {
    return candidateService.getResume(id);
  },

  async createInterview(
    payload: CreateInterviewRequest
  ): Promise<CreateInterviewResponse> {
    const data = await api.post<unknown>(
      "/interview/create",
      toCreateBody(payload)
    );
    return mapCreateInterviewResponse(data);
  },

  async planInterview(
    payload: PlanInterviewRequest,
    context?: {
      dossier: CandidateDossier;
      resume: ResumeDetails;
    }
  ): Promise<PlanInterviewResponse> {
    const data = await api.post<unknown>(
      "/interview/plan",
      toPlanBody(payload)
    );

    const fallbackCandidate = context
      ? mapPlanningCandidate(
          context.dossier,
          context.resume,
          payload.configuration.role
        )
      : {
          id: payload.candidateId,
          fullName: "",
          email: "",
          title: "",
          level: "",
          percentileLabel: "",
          avatarInitials: "AV",
          resumeScore: 0,
          readinessScore: 0,
          selectedRole: payload.configuration.role,
          resumeId: payload.resumeId,
          resumeFileName: null,
          resumeStatus: "unknown",
          resumeUploadedAt: null,
        };

    const plan: InterviewPlan = mapInterviewPlan(data, {
      configuration: payload.configuration,
      candidate: fallbackCandidate,
    });

    return { plan };
  },

  async getInterview(id: string): Promise<InterviewRoomSession> {
    const data = await api.get<unknown>(`/interview/${id}`);
    return mapInterviewRoomSession(data);
  },

  async getQuestions(interviewId: string): Promise<{
    questions: InterviewQuestion[];
    currentQuestion: InterviewQuestion | null;
    currentIndex: number;
  }> {
    const data = await api.get<unknown>(`/interview/${interviewId}/questions`);
    return mapQuestionsPayload(data);
  },

  async getTranscript(interviewId: string): Promise<TranscriptEntry[]> {
    const data = await api.get<unknown>(`/interview/${interviewId}/transcript`);
    return mapTranscriptPayload(data);
  },

  async getInterviewRoom(interviewId: string): Promise<InterviewRoomSession> {
    const [interview, questionsPayload, transcriptPayload] = await Promise.all([
      api.get<unknown>(`/interview/${interviewId}`),
      api.get<unknown>(`/interview/${interviewId}/questions`).catch(() => null),
      api.get<unknown>(`/interview/${interviewId}/transcript`).catch(() => null),
    ]);

    const base = mapInterviewRoomSession(interview);
    return mergeRoomSession({
      interview: base,
      questionsPayload: questionsPayload ?? undefined,
      transcriptPayload: transcriptPayload ?? undefined,
    });
  },

  async startInterview(
    payload: StartInterviewRequest
  ): Promise<StartInterviewResponse> {
    const data = await api.post<unknown>("/interview/start", {
      interview_id: payload.interviewId,
    });
    return mapStartInterviewResponse(data);
  },

  async endInterview(
    payload: EndInterviewRequest
  ): Promise<EndInterviewResponse> {
    const data = await api.post<unknown>("/interview/end", {
      interview_id: payload.interviewId,
      reason: payload.reason,
    });
    return mapEndInterviewResponse(data);
  },
};

function toPlanBody(payload: PlanInterviewRequest): Record<string, string | number> {
  return {
    candidate_id: payload.candidateId,
    resume_id: payload.resumeId,
    role: payload.configuration.role,
    difficulty: payload.configuration.difficulty,
    duration_minutes: payload.configuration.durationMinutes,
    question_count: payload.configuration.questionCount,
    interview_type: payload.configuration.interviewType,
  };
}

function toCreateBody(
  payload: CreateInterviewRequest
): Record<string, string | number | null> {
  return {
    candidate_id: payload.candidateId,
    resume_id: payload.resumeId,
    role: payload.configuration.role,
    complexity: payload.configuration.difficulty,
    duration_seconds: payload.configuration.durationMinutes * 60,
    question_count: payload.configuration.questionCount,
    interview_type: payload.configuration.interviewType,
    difficulty: payload.configuration.difficulty,
  };
}
