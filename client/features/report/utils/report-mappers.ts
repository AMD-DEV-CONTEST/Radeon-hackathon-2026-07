import type {
  CompetencyRadarPoint,
  GenerateReportResponse,
  HiringRecommendation,
  ImprovementItem,
  InterviewLookup,
  InterviewReport,
  PulsePoint,
  ReportCandidate,
  ReportScores,
  ScoreBreakdownItem,
  StrengthItem,
  TimelineEvent,
  TimelineEventType,
  TranscriptHighlight,
} from "@/features/report/types/report.types";

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

  if (
    normalized === "strong hire" ||
    normalized === "strong_hire" ||
    normalized === "stronghire"
  ) {
    return "Strong Hire";
  }
  if (normalized === "hire" || normalized === "recommend") {
    return "Hire";
  }
  if (normalized === "hold" || normalized === "maybe") {
    return "Hold";
  }
  if (
    normalized === "no hire" ||
    normalized === "no_hire" ||
    normalized === "reject"
  ) {
    return "No Hire";
  }
  return "Hold";
}

function mapCandidate(value: unknown): ReportCandidate {
  const record = isRecord(value) ? value : {};
  const fullName = asString(
    record.full_name ?? record.fullName ?? record.name
  ).trim();

  return {
    id: asString(record.id),
    fullName: fullName || "Candidate",
    title: asString(record.title ?? record.role),
    avatarInitials: asString(
      record.avatar_initials ?? record.avatarInitials,
      getInitials(fullName || "AV")
    ),
    avatarUrl: asString(record.avatar_url ?? record.avatarUrl) || undefined,
  };
}

function mapScores(value: unknown): ReportScores {
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
    leadership: asNumber(
      record.leadership ?? record.leadership_score ?? record.leadershipScore
    ),
    honesty: asNumber(
      record.honesty ?? record.honesty_score ?? record.honestyScore
    ),
  };
}

function mapCompetencyMatrix(
  value: unknown,
  scores: ReportScores
): CompetencyRadarPoint[] {
  if (Array.isArray(value) && value.length > 0) {
    return compactMap(
      value.map((item) => {
        if (!isRecord(item)) {
          return null;
        }
        const subject = asString(
          item.subject ?? item.label ?? item.name
        ).trim();
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
    { subject: "Leadership", score: scores.leadership, fullMark: 100 },
    {
      subject: "Problem Solving",
      score: scores.problemSolving,
      fullMark: 100,
    },
    { subject: "Confidence", score: scores.confidence, fullMark: 100 },
    { subject: "Honesty", score: scores.honesty, fullMark: 100 },
  ];
}

function mapScoreBreakdown(
  value: unknown,
  scores: ReportScores
): ScoreBreakdownItem[] {
  if (Array.isArray(value) && value.length > 0) {
    return compactMap(
      value.map((item) => {
        if (!isRecord(item)) {
          return null;
        }
        const keyRaw = asString(item.key ?? item.id).toLowerCase();
        const key: ScoreBreakdownItem["key"] =
          keyRaw === "communication" ||
          keyRaw === "leadership" ||
          keyRaw === "problemsolving" ||
          keyRaw === "problem_solving" ||
          keyRaw === "honesty" ||
          keyRaw === "behavioral" ||
          keyRaw === "confidence"
            ? keyRaw === "problem_solving" || keyRaw === "problemsolving"
              ? "problemSolving"
              : (keyRaw as ScoreBreakdownItem["key"])
            : "technical";

        return {
          key,
          label: asString(item.label ?? item.name, key),
          score: asNumber(item.score ?? item.value),
        };
      })
    );
  }

  return [
    { key: "technical", label: "Technical Depth", score: scores.technical },
    {
      key: "communication",
      label: "Communication",
      score: scores.communication,
    },
    { key: "leadership", label: "Leadership", score: scores.leadership },
    {
      key: "problemSolving",
      label: "Problem Solving",
      score: scores.problemSolving,
    },
    { key: "honesty", label: "Honesty", score: scores.honesty },
  ];
}

function mapPulse(value: unknown): PulsePoint[] {
  return compactMap(
    unwrapItems(value).map((item) => {
      if (!isRecord(item)) {
        return null;
      }
      return {
        minute: asNumber(item.minute ?? item.at_minute ?? item.t),
        engagement: asNumber(item.engagement ?? item.score),
        technicalDepth: asNumber(
          item.technical_depth ?? item.technicalDepth ?? item.technical
        ),
      };
    })
  );
}

function mapStrengthCategory(
  value: unknown
): StrengthItem["category"] {
  const normalized = asString(value).toLowerCase();
  if (normalized.includes("communication")) {
    return "Communication";
  }
  if (normalized.includes("leadership")) {
    return "Leadership";
  }
  if (normalized.includes("collab")) {
    return "Collaboration";
  }
  return "Technical";
}

function mapStrengths(value: unknown): StrengthItem[] {
  return compactMap(
    unwrapItems(value).map((item) => {
      if (typeof item === "string") {
        const title = item.trim();
        if (!title) {
          return null;
        }
        return {
          category: "Technical",
          title,
          description: title,
          score: 0,
        };
      }
      if (!isRecord(item)) {
        return null;
      }
      const title = asString(item.title ?? item.name ?? item.label).trim();
      if (!title) {
        return null;
      }
      return {
        category: mapStrengthCategory(item.category ?? item.type),
        title,
        description: asString(item.description ?? item.detail ?? item.summary),
        score: asNumber(item.score ?? item.value),
      };
    })
  );
}

function mapImprovementCategory(
  value: unknown
): ImprovementItem["category"] {
  const normalized = asString(value).toLowerCase();
  if (normalized.includes("soft")) {
    return "Soft Skills";
  }
  if (normalized.includes("communication")) {
    return "Communication";
  }
  if (normalized.includes("confidence")) {
    return "Confidence";
  }
  if (normalized.includes("time")) {
    return "Time Management";
  }
  return "Technical Gaps";
}

function mapSeverity(value: unknown): ImprovementItem["severity"] {
  const normalized = asString(value).toLowerCase();
  if (normalized === "high" || normalized === "medium" || normalized === "low") {
    return normalized;
  }
  return "medium";
}

function mapImprovements(value: unknown): ImprovementItem[] {
  return compactMap(
    unwrapItems(value).map((item) => {
      if (typeof item === "string") {
        const title = item.trim();
        if (!title) {
          return null;
        }
        return {
          category: "Technical Gaps",
          title,
          description: title,
          severity: "medium",
        };
      }
      if (!isRecord(item)) {
        return null;
      }
      const title = asString(item.title ?? item.name ?? item.label).trim();
      if (!title) {
        return null;
      }
      return {
        category: mapImprovementCategory(item.category ?? item.type),
        title,
        description: asString(item.description ?? item.detail ?? item.summary),
        severity: mapSeverity(item.severity ?? item.level),
      };
    })
  );
}

function mapHighlights(value: unknown): TranscriptHighlight[] {
  return compactMap(
    unwrapItems(value).map((item, index) => {
      if (!isRecord(item)) {
        return null;
      }
      const text = asString(item.text ?? item.content ?? item.message).trim();
      if (!text) {
        return null;
      }
      const speakerRaw = asString(item.speaker ?? item.role).toLowerCase();
      return {
        id: asString(item.id, `highlight-${index + 1}`),
        speaker:
          speakerRaw === "candidate" || speakerRaw === "user"
            ? "candidate"
            : "ai",
        timestamp: asString(item.timestamp ?? item.time ?? item.created_at),
        text,
        tag: asString(item.tag ?? item.label) || undefined,
      };
    })
  );
}

function mapTimelineType(value: unknown): TimelineEventType {
  const normalized = asString(value).toLowerCase();
  if (
    normalized === "question" ||
    normalized === "speaking" ||
    normalized === "evaluation" ||
    normalized === "milestone"
  ) {
    return normalized;
  }
  if (normalized.includes("question")) {
    return "question";
  }
  if (normalized.includes("speak")) {
    return "speaking";
  }
  if (normalized.includes("eval") || normalized.includes("score")) {
    return "evaluation";
  }
  return "milestone";
}

function mapTimeline(value: unknown): TimelineEvent[] {
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
        id: asString(item.id, `timeline-${index + 1}`),
        type: mapTimelineType(item.type ?? item.event_type),
        atMinute: asNumber(item.at_minute ?? item.atMinute ?? item.minute),
        title,
        description: asString(item.description ?? item.detail ?? item.summary),
      };
    })
  );
}

export function mapInterviewReport(dto: unknown): InterviewReport {
  const record = isRecord(dto) ? dto : {};
  const nested = isRecord(record.report) ? record.report : record;
  const scores = mapScores(
    nested.scores ?? nested.score_breakdown ?? nested.metrics ?? nested
  );
  const summaryRecord = isRecord(nested.summary)
    ? nested.summary
    : isRecord(nested.ai_summary)
      ? nested.ai_summary
      : {};

  const strengths = mapStrengths(
    nested.strengths ?? nested.strength_areas ?? nested.pros
  );
  const improvements = mapImprovements(
    nested.improvements ??
      nested.weaknesses ??
      nested.weakness_areas ??
      nested.cons
  );

  const candidate = mapCandidate(
    nested.candidate ?? nested.candidate_profile ?? nested.profile
  );

  return {
    id: asString(nested.id ?? nested.report_id ?? nested.reportId),
    interviewId: asString(
      nested.interview_id ??
        nested.interviewId ??
        (isRecord(nested.interview) ? nested.interview.id : nested.interview)
    ),
    interviewTitle: asString(
      nested.interview_title ?? nested.interviewTitle ?? nested.title,
      "Interview Report"
    ),
    conductedAt: asString(
      nested.conducted_at ?? nested.conductedAt ?? nested.created_at
    ),
    durationMinutes: asNumber(
      nested.duration_minutes ?? nested.durationMinutes ?? nested.duration
    ),
    candidate,
    recommendation: mapRecommendation(
      nested.recommendation ?? nested.hiring_recommendation
    ),
    performanceConfidence: asNumber(
      nested.performance_confidence ??
        nested.performanceConfidence ??
        nested.confidence_percent,
      scores.confidence
    ),
    insightQuote: asString(
      nested.insight_quote ?? nested.insightQuote ?? nested.quote
    ),
    scores,
    competencyMatrix: mapCompetencyMatrix(
      nested.competency_matrix ?? nested.competencyMatrix ?? nested.radar,
      scores
    ),
    scoreBreakdown: mapScoreBreakdown(
      nested.score_breakdown ?? nested.scoreBreakdown,
      scores
    ),
    interviewPulse: mapPulse(
      nested.interview_pulse ?? nested.interviewPulse ?? nested.pulse
    ),
    strengths,
    improvements,
    summary: {
      executive: asString(
        summaryRecord.executive ??
          nested.ai_summary ??
          nested.summary_text ??
          nested.summary
      ),
      overallPerformance: asString(
        summaryRecord.overall_performance ??
          summaryRecord.overallPerformance ??
          nested.overall_performance
      ),
      aiFeedback: asString(
        summaryRecord.ai_feedback ??
          summaryRecord.aiFeedback ??
          nested.ai_feedback
      ),
      finalRecommendation: asString(
        summaryRecord.final_recommendation ??
          summaryRecord.finalRecommendation ??
          nested.final_recommendation ??
          nested.recommendation
      ),
      executiveNote: asString(
        summaryRecord.executive_note ??
          summaryRecord.executiveNote ??
          nested.executive_note
      ),
    },
    transcriptHighlights: mapHighlights(
      nested.transcript_highlights ??
        nested.transcriptHighlights ??
        nested.highlights
    ),
    timeline: mapTimeline(nested.timeline ?? nested.events),
  };
}

export function mapGenerateReportResponse(
  dto: unknown
): GenerateReportResponse {
  const record = isRecord(dto) ? dto : {};
  const statusRaw = asString(record.status, "queued").toLowerCase();
  const status: GenerateReportResponse["status"] =
    statusRaw === "ready" || statusRaw === "generating" || statusRaw === "queued"
      ? statusRaw
      : "queued";

  return {
    reportId: asString(
      record.report_id ?? record.reportId ?? record.id
    ),
    status,
    interviewId: asString(record.interview_id ?? record.interviewId),
  };
}

export function mapInterviewLookup(dto: unknown): InterviewLookup {
  const record = isRecord(dto) ? dto : {};
  const nested = isRecord(record.interview) ? record.interview : record;
  const candidate = isRecord(nested.candidate) ? nested.candidate : {};
  const statusRaw = asString(nested.status).toLowerCase();

  const status: InterviewLookup["status"] =
    statusRaw === "cancelled" || statusRaw === "canceled"
      ? "cancelled"
      : statusRaw === "in_progress" ||
          statusRaw === "live" ||
          statusRaw === "active"
        ? "in_progress"
        : "completed";

  return {
    id: asString(nested.id ?? record.id),
    title: asString(
      nested.title ?? nested.interview_title ?? nested.role,
      "Interview"
    ),
    candidateName: asString(
      nested.candidate_name ??
        nested.candidateName ??
        candidate.full_name ??
        candidate.fullName ??
        candidate.name
    ),
    status,
    durationMinutes: asNumber(
      nested.duration_minutes ?? nested.durationMinutes ?? nested.duration
    ),
    conductedAt: asString(
      nested.conducted_at ??
        nested.conductedAt ??
        nested.ended_at ??
        nested.created_at
    ),
  };
}
