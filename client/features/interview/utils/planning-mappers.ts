import type { CandidateDossier } from "@/features/candidate/types/candidate.types";
import type { ResumeDetails } from "@/features/candidate/types/candidate.types";
import type {
  AgentStatus,
  ChecklistItem,
  CoveragePoint,
  CreateInterviewRequest,
  CreateInterviewResponse,
  InterviewAgent,
  InterviewConfiguration,
  InterviewDifficulty,
  InterviewPlan,
  InterviewType,
  MetricBar,
  PlanInterviewRequest,
  PlanningCandidate,
  PlanningInsight,
  PlanningSummary,
  WorkflowStep,
  WorkflowStepStatus,
} from "@/features/interview/types/interview.types";

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

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => asString(item).trim())
    .filter((item) => item.length > 0);
}

function compactMap<T>(values: ReadonlyArray<T | null>): T[] {
  return values.filter((value): value is T => value !== null);
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

function mapDifficulty(value: unknown): InterviewDifficulty {
  const normalized = asString(value).toLowerCase();
  if (
    normalized === "easy" ||
    normalized === "medium" ||
    normalized === "hard" ||
    normalized === "extreme"
  ) {
    return normalized;
  }
  if (normalized === "low") {
    return "easy";
  }
  if (normalized === "high") {
    return "hard";
  }
  return "medium";
}

function mapInterviewType(value: unknown): InterviewType {
  const normalized = asString(value).toLowerCase();
  if (
    normalized === "technical" ||
    normalized === "behavioral" ||
    normalized === "mixed"
  ) {
    return normalized;
  }
  return "mixed";
}

function mapAgentStatus(value: unknown): AgentStatus {
  const normalized = asString(value).toLowerCase();
  if (
    normalized === "idle" ||
    normalized === "running" ||
    normalized === "ready" ||
    normalized === "blocked"
  ) {
    return normalized;
  }
  return "idle";
}

function mapWorkflowStatus(value: unknown): WorkflowStepStatus {
  const normalized = asString(value).toLowerCase();
  if (
    normalized === "completed" ||
    normalized === "active" ||
    normalized === "pending"
  ) {
    return normalized;
  }
  return "pending";
}

function mapMetricBars(value: unknown): MetricBar[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return compactMap(
    value.map((item) => {
      if (typeof item === "string") {
        const label = item.trim();
        return label ? { label, value: 0 } : null;
      }
      if (!isRecord(item)) {
        return null;
      }
      const label = asString(item.label ?? item.name ?? item.skill).trim();
      if (!label) {
        return null;
      }
      return {
        label,
        value: asNumber(item.value ?? item.score ?? item.coverage),
      };
    })
  );
}

function mapCoverage(value: unknown): CoveragePoint[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return compactMap(
    value.map((item) => {
      if (typeof item === "string") {
        const label = item.trim();
        return label ? { label, coverage: 0 } : null;
      }
      if (!isRecord(item)) {
        return null;
      }
      const label = asString(item.label ?? item.name ?? item.skill).trim();
      if (!label) {
        return null;
      }
      return {
        label,
        coverage: asNumber(item.coverage ?? item.value ?? item.score),
      };
    })
  );
}

function mapAgents(value: unknown): InterviewAgent[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return compactMap(
    value.map((item, index) => {
      if (!isRecord(item)) {
        return null;
      }
      return {
        id: asString(item.id, `agent-${index}`),
        name: asString(item.name),
        description: asString(item.description),
        status: mapAgentStatus(item.status),
        progress: asNumber(item.progress),
        ready: Boolean(item.ready),
      };
    })
  );
}

function mapWorkflow(value: unknown): WorkflowStep[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return compactMap(
    value.map((item, index) => {
      if (!isRecord(item)) {
        return null;
      }

      const iconRaw = asString(item.icon, "planning");
      const icon: WorkflowStep["icon"] =
        iconRaw === "resume" ||
        iconRaw === "planning" ||
        iconRaw === "questions" ||
        iconRaw === "difficulty" ||
        iconRaw === "graph" ||
        iconRaw === "ready"
          ? iconRaw
          : "planning";

      return {
        id: asString(item.id, `step-${index + 1}`),
        step: asString(item.step, String(index + 1).padStart(2, "0")),
        title: asString(item.title),
        status: mapWorkflowStatus(item.status),
        icon,
      };
    })
  );
}

function mapChecklist(value: unknown): ChecklistItem[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return compactMap(
    value.map((item, index) => {
      if (!isRecord(item)) {
        return null;
      }
      return {
        id: asString(item.id, `check-${index}`),
        label: asString(item.label ?? item.name),
        completed: Boolean(item.completed ?? item.done),
      };
    })
  );
}

function mapInsights(value: unknown): PlanningInsight {
  if (!isRecord(value)) {
    return {
      suggestions: [],
      strengths: [],
      gaps: [],
      strategy: "",
      recommendation: "",
    };
  }

  return {
    suggestions: asStringArray(
      value.suggestions ?? value.ai_suggestions ?? value.aiSuggestions
    ),
    strengths: mapMetricBars(value.strengths),
    gaps: mapMetricBars(value.gaps),
    strategy: asString(value.strategy),
    recommendation: asString(value.recommendation),
  };
}

function mapSummary(
  value: unknown,
  configuration: InterviewConfiguration
): PlanningSummary {
  if (!isRecord(value)) {
    return {
      estimatedDurationMinutes: configuration.durationMinutes,
      expectedQuestionCount: configuration.questionCount,
      skillCoverage: 0,
      confidenceScore: 0,
      planningProgress: 0,
      engineStatus: "READY",
      difficulty: configuration.difficulty,
      skillsToCover: [],
    };
  }

  return {
    estimatedDurationMinutes: asNumber(
      value.estimated_duration_minutes ??
        value.estimatedDurationMinutes ??
        value.duration_minutes ??
        configuration.durationMinutes
    ),
    expectedQuestionCount: asNumber(
      value.expected_question_count ??
        value.expectedQuestionCount ??
        value.question_count ??
        configuration.questionCount
    ),
    skillCoverage: asNumber(value.skill_coverage ?? value.skillCoverage),
    confidenceScore: asNumber(
      value.confidence_score ?? value.confidenceScore
    ),
    planningProgress: asNumber(
      value.planning_progress ?? value.planningProgress
    ),
    engineStatus: asString(value.engine_status ?? value.engineStatus, "READY"),
    difficulty: mapDifficulty(
      value.difficulty ?? configuration.difficulty
    ),
    skillsToCover: asStringArray(
      value.skills_to_cover ?? value.skillsToCover
    ),
  };
}

export function mapPlanningCandidate(
  dossier: CandidateDossier,
  resume: ResumeDetails | null,
  selectedRole: string
): PlanningCandidate {
  const profile = dossier.profile;

  return {
    id: profile.id,
    fullName: profile.fullName,
    title: profile.title,
    level:
      profile.yearsOfExperience > 0
        ? `${profile.yearsOfExperience}+ yrs`
        : profile.title,
    percentileLabel: dossier.analysisStatus === "complete" ? "Analyzed" : "Pending",
    avatarInitials: profile.avatarInitials,
    resumeScore: 0,
    readinessScore: dossier.roadmap.readinessScore,
    selectedRole: selectedRole || profile.targetRole,
    email: profile.email,
    resumeId: resume?.id ?? profile.resumeId,
    resumeFileName: resume?.fileName ?? null,
    resumeStatus: resume?.status ?? "unknown",
    resumeUploadedAt: resume?.uploadedAt ?? null,
  };
}

/** Prefer explicit resume/readiness scores when present on dossier-like payloads. */
export function enrichPlanningCandidateScores(
  candidate: PlanningCandidate,
  source: unknown
): PlanningCandidate {
  if (!isRecord(source)) {
    return candidate;
  }

  return {
    ...candidate,
    resumeScore: asNumber(
      source.resume_score ?? source.resumeScore,
      candidate.resumeScore
    ),
    readinessScore: asNumber(
      source.readiness_score ??
        source.ai_readiness_score ??
        source.readinessScore,
      candidate.readinessScore
    ),
  };
}

export function toBackendPlanRequest(
  payload: PlanInterviewRequest
): Record<string, string | number> {
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

export function toBackendCreateRequest(
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

export function mapCreateInterviewResponse(
  dto: unknown
): CreateInterviewResponse {
  const record = isRecord(dto) ? dto : {};
  const interviewId = asString(
    record.interview_id ?? record.interviewId ?? record.id
  );
  const statusRaw = asString(record.status, "created").toLowerCase();

  return {
    interviewId,
    status: statusRaw === "queued" ? "queued" : "created",
  };
}

export function mapInterviewPlan(
  dto: unknown,
  options: {
    configuration: InterviewConfiguration;
    candidate: PlanningCandidate;
  }
): InterviewPlan {
  const record = isRecord(dto) ? dto : {};
  const planRoot = isRecord(record.plan) ? record.plan : record;
  const configurationFromPlan = isRecord(planRoot.configuration)
    ? planRoot.configuration
    : null;

  const configuration: InterviewConfiguration = {
    role: asString(
      configurationFromPlan?.role,
      options.configuration.role
    ),
    difficulty: mapDifficulty(
      configurationFromPlan?.difficulty ??
        planRoot.difficulty ??
        options.configuration.difficulty
    ),
    durationMinutes: asNumber(
      configurationFromPlan?.duration_minutes ??
        configurationFromPlan?.durationMinutes ??
        planRoot.estimated_duration_minutes ??
        options.configuration.durationMinutes
    ),
    questionCount: asNumber(
      configurationFromPlan?.question_count ??
        configurationFromPlan?.questionCount ??
        options.configuration.questionCount
    ),
    interviewType: mapInterviewType(
      configurationFromPlan?.interview_type ??
        configurationFromPlan?.interviewType ??
        options.configuration.interviewType
    ),
  };

  const skillsToCover = asStringArray(
    planRoot.skills_to_cover ?? planRoot.skillsToCover
  );
  const summary = mapSummary(planRoot.summary ?? planRoot, configuration);
  const skillDistribution =
    mapMetricBars(
      planRoot.skill_distribution ?? planRoot.skillDistribution
    ).length > 0
      ? mapMetricBars(
          planRoot.skill_distribution ?? planRoot.skillDistribution
        )
      : skillsToCover.map((label) => ({ label, value: 0 }));

  const interviewCoverage =
    mapCoverage(
      planRoot.interview_coverage ?? planRoot.interviewCoverage
    ).length > 0
      ? mapCoverage(
          planRoot.interview_coverage ?? planRoot.interviewCoverage
        )
      : skillsToCover.map((label) => ({ label, coverage: 0 }));

  const mappedInsights = mapInsights(planRoot.insights ?? planRoot);
  const insights: PlanningInsight = {
    ...mappedInsights,
    suggestions:
      mappedInsights.suggestions.length > 0
        ? mappedInsights.suggestions
        : asStringArray(
            planRoot.ai_suggestions ??
              planRoot.aiSuggestions ??
              planRoot.suggestions
          ),
  };

  const candidate = enrichPlanningCandidateScores(
    {
      ...options.candidate,
      selectedRole: configuration.role || options.candidate.selectedRole,
    },
    planRoot.candidate ?? planRoot
  );

  return {
    id: asString(planRoot.id ?? planRoot.plan_id ?? planRoot.interview_id),
    candidate,
    configuration,
    agents: mapAgents(planRoot.agents),
    workflow: mapWorkflow(planRoot.workflow),
    checklist: mapChecklist(planRoot.checklist),
    summary: {
      ...summary,
      skillsToCover:
        summary.skillsToCover.length > 0
          ? summary.skillsToCover
          : skillsToCover,
      difficulty: configuration.difficulty,
    },
    skillDistribution,
    interviewCoverage,
    insights,
  };
}

export function buildFallbackPlan(
  candidate: PlanningCandidate,
  configuration: InterviewConfiguration
): InterviewPlan {
  return {
    id: "",
    candidate: {
      ...candidate,
      selectedRole: configuration.role || candidate.selectedRole,
    },
    configuration,
    agents: [],
    workflow: [],
    checklist: [
      {
        id: "resume",
        label: "Resume Uploaded",
        completed: Boolean(candidate.resumeId),
      },
      { id: "config", label: "Configuration Set", completed: Boolean(configuration.role) },
      { id: "plan", label: "Interview Plan Generated", completed: false },
    ],
    summary: {
      estimatedDurationMinutes: configuration.durationMinutes,
      expectedQuestionCount: configuration.questionCount,
      skillCoverage: 0,
      confidenceScore: 0,
      planningProgress: 0,
      engineStatus: "AWAITING PLAN",
      difficulty: configuration.difficulty,
      skillsToCover: [],
    },
    skillDistribution: [],
    interviewCoverage: [],
    insights: {
      suggestions: [],
      strengths: [],
      gaps: [],
      strategy: "",
      recommendation: "",
    },
  };
}
