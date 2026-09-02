import type { CandidateDossier } from "@/features/candidate/types/candidate.types";
import type {
  AiInsights,
  CompetencyPoint,
  CompletionStatus,
  EvaluationTimelinePoint,
  HiringRecommendation,
  ImprovementSuggestion,
  InterviewHighlight,
  PipelineStage,
  PipelineStageStatus,
  PresentationCandidate,
  PresentationCandidateLookup,
  PresentationDashboard,
  PresentationReportLookup,
  PresentationScores,
  ScoreTrendPoint,
  SkillBreakdownItem,
} from "@/features/presentation/types/presentation.types";
import type { InterviewReport } from "@/features/report/types/report.types";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function asString(value: unknown, fallback = ""): string {
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return fallback;
}

function asNumber(value: unknown, fallback = 0): number {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim().length > 0) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  return fallback;
}

function compactMap<T>(values: ReadonlyArray<T | null>): T[] {
  return values.filter((value): value is T => value !== null);
}

function unwrapItems(payload: unknown): unknown[] {
  if (Array.isArray(payload)) {
    return payload;
  }
  if (isRecord(payload) && Array.isArray(payload.items)) {
    return payload.items;
  }
  if (isRecord(payload) && Array.isArray(payload.data)) {
    return payload.data;
  }
  return [];
}

function getInitials(fullName: string): string {
  const parts = fullName.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) {
    return "AV";
  }
  if (parts.length === 1) {
    return parts[0].slice(0, 2).toUpperCase();
  }
  return `${parts[0][0] ?? ""}${parts[1][0] ?? ""}`.toUpperCase();
}

function mapRecommendation(value: unknown): HiringRecommendation {
  const normalized = asString(value)
    .toLowerCase()
    .replace(/[_-]+/g, " ")
    .trim();

  if (normalized.includes("strong")) {
    return "Strong Hire";
  }
  if (normalized === "hire" || normalized === "recommend") {
    return "Hire";
  }
  if (normalized === "hold" || normalized === "maybe") {
    return "Hold";
  }
  if (normalized.includes("no hire") || normalized === "reject") {
    return "No Hire";
  }
  return "Hold";
}

function mapCompletionStatus(value: unknown): CompletionStatus {
  const normalized = asString(value).toLowerCase();
  if (normalized === "partial") {
    return "partial";
  }
  if (normalized === "abandoned" || normalized === "cancelled") {
    return "abandoned";
  }
  return "completed";
}

function mapCandidate(value: unknown): PresentationCandidate {
  const record = isRecord(value) ? value : {};
  const fullName = asString(
    record.full_name ?? record.fullName ?? record.name
  ).trim();

  return {
    id: asString(record.id),
    fullName: fullName || "Candidate",
    appliedRole: asString(
      record.applied_role ?? record.appliedRole ?? record.title ?? record.role
    ),
    company: asString(record.company ?? record.organization),
    avatarInitials: asString(
      record.avatar_initials ?? record.avatarInitials,
      getInitials(fullName || "AV")
    ),
    interviewDate: asString(
      record.interview_date ??
        record.interviewDate ??
        record.conducted_at ??
        record.created_at
    ),
  };
}

function mapScores(value: unknown): PresentationScores {
  const record = isRecord(value) ? value : {};

  return {
    overall: asNumber(
      record.overall ?? record.overall_score ?? record.overallScore
    ),
    technical: asNumber(
      record.technical ?? record.technical_score ?? record.technicalScore
    ),
    communication: asNumber(
      record.communication ??
        record.communication_score ??
        record.communicationScore
    ),
    behavioral: asNumber(
      record.behavioral ?? record.behavioral_score ?? record.behavioralScore
    ),
    confidence: asNumber(
      record.confidence ?? record.confidence_score ?? record.confidenceScore
    ),
    problemSolving: asNumber(
      record.problem_solving ??
        record.problemSolving ??
        record.problem_solving_score
    ),
    collaboration: asNumber(
      record.collaboration ??
        record.collaboration_score ??
        record.collaborationScore
    ),
  };
}

function mapCompetencyMatrix(
  value: unknown,
  scores: PresentationScores
): CompetencyPoint[] {
  if (Array.isArray(value) && value.length > 0) {
    return compactMap(
      value.map((item) => {
        if (!isRecord(item)) {
          return null;
        }
        const subject = asString(item.subject ?? item.label ?? item.name).trim();
        if (!subject) {
          return null;
        }
        return {
          subject,
          score: asNumber(item.score ?? item.value),
          fullMark: asNumber(item.full_mark ?? item.fullMark, 100),
        };
      })
    );
  }

  return [
    { subject: "Technical", score: scores.technical, fullMark: 100 },
    { subject: "Communication", score: scores.communication, fullMark: 100 },
    { subject: "Behavioral", score: scores.behavioral, fullMark: 100 },
    { subject: "Confidence", score: scores.confidence, fullMark: 100 },
    {
      subject: "Problem Solving",
      score: scores.problemSolving,
      fullMark: 100,
    },
    { subject: "Collaboration", score: scores.collaboration, fullMark: 100 },
  ];
}

function mapSkillBreakdown(value: unknown): SkillBreakdownItem[] {
  return compactMap(
    unwrapItems(value).map((item) => {
      if (!isRecord(item)) {
        return null;
      }
      const label = asString(item.label ?? item.name ?? item.skill).trim();
      if (!label) {
        return null;
      }
      return {
        label,
        score: asNumber(item.score ?? item.value),
      };
    })
  );
}

function mapScoreTrend(value: unknown): ScoreTrendPoint[] {
  return compactMap(
    unwrapItems(value).map((item) => {
      if (!isRecord(item)) {
        return null;
      }
      const label = asString(item.label ?? item.name ?? item.question).trim();
      if (!label) {
        return null;
      }
      return {
        label,
        score: asNumber(item.score ?? item.value),
      };
    })
  );
}

function mapEvaluationTimeline(value: unknown): EvaluationTimelinePoint[] {
  return compactMap(
    unwrapItems(value).map((item) => {
      if (!isRecord(item)) {
        return null;
      }
      return {
        minute: asNumber(item.minute ?? item.at_minute ?? item.t),
        engagement: asNumber(item.engagement ?? item.score),
        technical: asNumber(
          item.technical ?? item.technical_depth ?? item.technicalDepth
        ),
      };
    })
  );
}

function mapStringList(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => {
      if (typeof item === "string") {
        return item.trim();
      }
      if (isRecord(item)) {
        return asString(item.title ?? item.name ?? item.label ?? item.text).trim();
      }
      return "";
    })
    .filter((item) => item.length > 0);
}

function mapInsights(value: unknown): AiInsights {
  const record = isRecord(value) ? value : {};
  return {
    strengths: mapStringList(record.strengths ?? record.strength_areas),
    weaknesses: mapStringList(
      record.weaknesses ?? record.weakness_areas ?? record.improvements
    ),
    keyObservations: mapStringList(
      record.key_observations ?? record.keyObservations ?? record.observations
    ),
    redFlags: mapStringList(record.red_flags ?? record.redFlags),
    positiveSignals: mapStringList(
      record.positive_signals ?? record.positiveSignals ?? record.signals
    ),
  };
}

function mapHighlights(value: unknown): InterviewHighlight[] {
  return compactMap(
    unwrapItems(value).map((item, index) => {
      if (!isRecord(item)) {
        return null;
      }
      const title = asString(item.title ?? item.name ?? item.label).trim();
      if (!title) {
        return null;
      }
      return {
        id: asString(item.id, `highlight-${index + 1}`),
        label: asString(item.label ?? item.tag, "Highlight"),
        title,
        detail: asString(item.detail ?? item.description ?? item.summary),
      };
    })
  );
}

function mapImprovements(value: unknown): ImprovementSuggestion[] {
  return compactMap(
    unwrapItems(value).map((item, index) => {
      if (typeof item === "string") {
        const suggestion = item.trim();
        if (!suggestion) {
          return null;
        }
        return {
          id: `improvement-${index + 1}`,
          area: "General",
          suggestion,
          priority: "medium",
        };
      }
      if (!isRecord(item)) {
        return null;
      }
      const suggestion = asString(
        item.suggestion ?? item.description ?? item.title ?? item.summary
      ).trim();
      if (!suggestion) {
        return null;
      }
      const priorityRaw = asString(item.priority ?? item.severity).toLowerCase();
      const priority: ImprovementSuggestion["priority"] =
        priorityRaw === "high" || priorityRaw === "low" ? priorityRaw : "medium";

      return {
        id: asString(item.id, `improvement-${index + 1}`),
        area: asString(item.area ?? item.category ?? item.label, "General"),
        suggestion,
        priority,
      };
    })
  );
}

function mapPipelineStatus(value: unknown): PipelineStageStatus {
  const normalized = asString(value).toLowerCase();
  if (normalized === "completed" || normalized === "done") {
    return "completed";
  }
  if (normalized === "active" || normalized === "current") {
    return "active";
  }
  return "upcoming";
}

function mapPipeline(value: unknown): PipelineStage[] {
  return compactMap(
    unwrapItems(value).map((item, index) => {
      if (!isRecord(item)) {
        return null;
      }
      const label = asString(item.label ?? item.name ?? item.stage).trim();
      if (!label) {
        return null;
      }
      return {
        id: asString(item.id, `stage-${index + 1}`),
        label,
        status: mapPipelineStatus(item.status),
        completedAt: asString(item.completed_at ?? item.completedAt) || undefined,
      };
    })
  );
}

export function mapPresentationDashboard(dto: unknown): PresentationDashboard {
  const record = isRecord(dto) ? dto : {};
  const nested = isRecord(record.presentation)
    ? record.presentation
    : isRecord(record.dashboard)
      ? record.dashboard
      : record;

  const scores = mapScores(
    nested.scores ?? nested.score_breakdown ?? nested.metrics ?? nested
  );

  const insights = mapInsights(
    nested.insights ?? nested.ai_insights ?? nested.aiInsights ?? nested
  );

  return {
    id: asString(nested.id ?? nested.presentation_id ?? nested.presentationId),
    reportId: asString(nested.report_id ?? nested.reportId),
    candidate: mapCandidate(nested.candidate ?? nested.candidate_profile),
    recommendation: mapRecommendation(
      nested.recommendation ?? nested.hiring_recommendation
    ),
    recommendationExplanation: asString(
      nested.recommendation_explanation ??
        nested.recommendationExplanation ??
        nested.explanation
    ),
    scores,
    executiveSummary: asString(
      nested.executive_summary ??
        nested.executiveSummary ??
        nested.summary ??
        nested.ai_summary
    ),
    durationMinutes: asNumber(
      nested.duration_minutes ?? nested.durationMinutes ?? nested.duration
    ),
    totalQuestions: asNumber(
      nested.total_questions ?? nested.totalQuestions ?? nested.question_count
    ),
    completionStatus: mapCompletionStatus(
      nested.completion_status ?? nested.completionStatus ?? nested.status
    ),
    competencyMatrix: mapCompetencyMatrix(
      nested.competency_matrix ?? nested.competencyMatrix ?? nested.radar,
      scores
    ),
    skillBreakdown: mapSkillBreakdown(
      nested.skill_breakdown ?? nested.skillBreakdown ?? nested.skills
    ),
    scoreTrend: mapScoreTrend(
      nested.score_trend ?? nested.scoreTrend ?? nested.trend
    ),
    evaluationTimeline: mapEvaluationTimeline(
      nested.evaluation_timeline ??
        nested.evaluationTimeline ??
        nested.timeline ??
        nested.interview_pulse
    ),
    insights: {
      ...insights,
      strengths:
        insights.strengths.length > 0
          ? insights.strengths
          : mapStringList(nested.strengths),
      weaknesses:
        insights.weaknesses.length > 0
          ? insights.weaknesses
          : mapStringList(nested.weaknesses),
    },
    highlights: mapHighlights(
      nested.highlights ?? nested.interview_highlights
    ),
    improvements: mapImprovements(
      nested.improvements ?? nested.weaknesses ?? nested.suggestions
    ),
    pipeline: mapPipeline(nested.pipeline ?? nested.hiring_pipeline),
    lastSyncedAt: asString(
      nested.last_synced_at ?? nested.lastSyncedAt ?? nested.updated_at,
      new Date().toISOString()
    ),
  };
}

export function mapPresentationReportLookup(
  report: InterviewReport
): PresentationReportLookup {
  return {
    id: report.id,
    candidateId: report.candidate.id,
    recommendation: report.recommendation,
    overallScore: report.scores.overall,
  };
}

export function mapPresentationCandidateLookup(
  dossier: CandidateDossier
): PresentationCandidateLookup {
  return {
    id: dossier.profile.id,
    fullName: dossier.profile.fullName,
    appliedRole: dossier.profile.targetRole || dossier.profile.title,
    company: dossier.experience[0]?.company ?? "",
  };
}

export function mergePresentationDashboard(options: {
  presentation: PresentationDashboard;
  report?: PresentationReportLookup | null;
  candidate?: PresentationCandidateLookup | null;
}): PresentationDashboard {
  const { presentation, report, candidate } = options;

  return {
    ...presentation,
    reportId: report?.id || presentation.reportId,
    recommendation: report?.recommendation || presentation.recommendation,
    scores: {
      ...presentation.scores,
      overall: report?.overallScore || presentation.scores.overall,
    },
    candidate: {
      ...presentation.candidate,
      id: candidate?.id || presentation.candidate.id,
      fullName: candidate?.fullName || presentation.candidate.fullName,
      appliedRole: candidate?.appliedRole || presentation.candidate.appliedRole,
      company: candidate?.company || presentation.candidate.company,
    },
  };
}
