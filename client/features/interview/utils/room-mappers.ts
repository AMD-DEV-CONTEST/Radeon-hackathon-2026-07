import type {
  EndInterviewResponse,
  InterviewDifficulty,
  InterviewQuestion,
  InterviewRoomCandidate,
  InterviewRoomPhase,
  InterviewRoomSession,
  LiveMetric,
  LiveMetricPoint,
  RoomAgent,
  RoomAgentStatus,
  StartInterviewResponse,
  TranscriptEntry,
  TranscriptSpeaker,
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

function unwrapItems(payload: unknown): unknown[] {
  if (Array.isArray(payload)) {
    return payload;
  }
  if (isRecord(payload) && Array.isArray(payload.items)) {
    return payload.items;
  }
  if (isRecord(payload) && Array.isArray(payload.questions)) {
    return payload.questions;
  }
  if (isRecord(payload) && Array.isArray(payload.transcript)) {
    return payload.transcript;
  }
  if (isRecord(payload) && Array.isArray(payload.entries)) {
    return payload.entries;
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

function mapSpeaker(value: unknown): TranscriptSpeaker {
  const normalized = asString(value).toLowerCase();
  if (
    normalized === "candidate" ||
    normalized === "user" ||
    normalized === "human"
  ) {
    return "candidate";
  }
  return "ai";
}

function mapRoomAgentStatus(value: unknown): RoomAgentStatus {
  const normalized = asString(value).toLowerCase();
  if (
    normalized === "active" ||
    normalized === "waiting" ||
    normalized === "completed"
  ) {
    return normalized;
  }
  if (normalized === "running") {
    return "active";
  }
  if (normalized === "done" || normalized === "ready") {
    return "completed";
  }
  return "waiting";
}

function mapSessionStatus(
  value: unknown
): InterviewRoomSession["status"] {
  const normalized = asString(value).toLowerCase();
  if (
    normalized === "completed" ||
    normalized === "ended" ||
    normalized === "finished"
  ) {
    return "ended";
  }
  if (normalized === "cancelled" || normalized === "canceled") {
    return "cancelled";
  }
  if (normalized === "scheduled" || normalized === "created") {
    return "scheduled";
  }
  if (normalized === "live" || normalized === "in_progress" || normalized === "active") {
    return "live";
  }
  return "live";
}

export function mapPhaseFromStatus(
  status: InterviewRoomSession["status"]
): InterviewRoomPhase {
  if (status === "ended") {
    return "ended";
  }
  if (status === "cancelled") {
    return "cancelled";
  }
  if (status === "scheduled") {
    return "loading";
  }
  return "live";
}

function mapCandidate(value: unknown): InterviewRoomCandidate {
  const record = isRecord(value) ? value : {};
  const fullName = asString(
    record.full_name ?? record.fullName ?? record.name
  ).trim();

  return {
    id: asString(record.id),
    fullName: fullName || "Candidate",
    shortName: asString(record.short_name ?? record.shortName, fullName),
    title: asString(record.title ?? record.role),
    level: asString(record.level),
    skills: asStringArray(record.skills),
    avatarInitials: asString(
      record.avatar_initials ?? record.avatarInitials,
      getInitials(fullName || "AV")
    ),
  };
}

export function mapInterviewQuestion(
  value: unknown,
  fallbackIndex = 1,
  fallbackTotal = 1
): InterviewQuestion {
  const record = isRecord(value) ? value : {};

  return {
    id: asString(record.id, `q-${fallbackIndex}`),
    index: asNumber(record.index ?? record.number ?? record.order, fallbackIndex),
    total: asNumber(record.total ?? record.total_questions, fallbackTotal),
    topic: asString(record.topic ?? record.category ?? record.title),
    difficulty: mapDifficulty(record.difficulty ?? record.complexity),
    prompt: asString(record.prompt ?? record.question ?? record.content),
    evaluatorNotes: asString(
      record.evaluator_notes ?? record.evaluatorNotes ?? record.notes
    ),
    elapsedSeconds: asNumber(
      record.elapsed_seconds ?? record.elapsedSeconds ?? record.elapsed
    ),
  };
}

export function mapQuestionsPayload(payload: unknown): {
  questions: InterviewQuestion[];
  currentQuestion: InterviewQuestion | null;
  currentIndex: number;
} {
  const items = unwrapItems(payload);
  const total = items.length || 1;
  const questions = items.map((item, index) =>
    mapInterviewQuestion(item, index + 1, total)
  );

  const root = isRecord(payload) ? payload : {};
  const explicitIndex = asNumber(
    root.current_index ?? root.currentIndex ?? root.active_index
  );
  const currentFromRoot = isRecord(root.current_question)
    ? mapInterviewQuestion(
        root.current_question,
        explicitIndex || 1,
        total
      )
    : null;

  const currentQuestion =
    currentFromRoot ??
    (explicitIndex > 0
      ? questions.find((question) => question.index === explicitIndex) ?? null
      : null) ??
    questions[0] ??
    null;

  return {
    questions,
    currentQuestion,
    currentIndex: currentQuestion?.index ?? (explicitIndex || 1),
  };
}

export function mapTranscriptPayload(payload: unknown): TranscriptEntry[] {
  return compactMap(
    unwrapItems(payload).map((item, index) => {
      if (!isRecord(item)) {
        return null;
      }

      const content = asString(item.content ?? item.text ?? item.message).trim();
      if (!content) {
        return null;
      }

      const speaker = mapSpeaker(item.speaker ?? item.role);
      return {
        id: asString(item.id, `t-${index + 1}`),
        speaker,
        speakerLabel: asString(
          item.speaker_label ?? item.speakerLabel,
          speaker === "ai" ? "AI AGENT" : "CANDIDATE"
        ),
        timestamp: asString(item.timestamp ?? item.created_at ?? item.time),
        content,
        accuracy:
          item.accuracy === undefined || item.accuracy === null
            ? undefined
            : asNumber(item.accuracy),
      };
    })
  );
}

function mapMetrics(value: unknown): LiveMetric[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return compactMap(
    value.map((item, index) => {
      if (!isRecord(item)) {
        return null;
      }
      const label = asString(item.label ?? item.name).trim();
      if (!label) {
        return null;
      }
      const iconRaw = asString(item.icon, "technical").toLowerCase();
      const icon: LiveMetric["icon"] =
        iconRaw === "communication" ||
        iconRaw === "confidence" ||
        iconRaw === "leadership" ||
        iconRaw === "quality"
          ? iconRaw
          : "technical";

      return {
        id: asString(item.id, `metric-${index}`),
        label,
        score: asNumber(item.score ?? item.value),
        delta: asNumber(item.delta ?? item.change),
        icon,
      };
    })
  );
}

function mapMetricSeries(value: unknown): LiveMetricPoint[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return compactMap(
    value.map((item) => {
      if (!isRecord(item)) {
        return null;
      }
      return {
        time: asString(item.time ?? item.label),
        confidence: asNumber(item.confidence),
        communication: asNumber(item.communication),
        technical: asNumber(item.technical),
      };
    })
  );
}

function mapAgents(value: unknown): RoomAgent[] {
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
        status: mapRoomAgentStatus(item.status),
        progress: asNumber(item.progress),
        currentTask: asString(item.current_task ?? item.currentTask ?? item.task),
      };
    })
  );
}

function emptyQuestion(): InterviewQuestion {
  return {
    id: "q-pending",
    index: 0,
    total: 0,
    topic: "",
    difficulty: "medium",
    prompt: "Waiting for the next question...",
    evaluatorNotes: "",
    elapsedSeconds: 0,
  };
}

export function mapInterviewRoomSession(
  dto: unknown,
  options: {
    questions?: InterviewQuestion[];
    currentQuestion?: InterviewQuestion | null;
    transcript?: TranscriptEntry[];
  } = {}
): InterviewRoomSession {
  const record = isRecord(dto) ? dto : {};
  const nestedSession = isRecord(record.session) ? record.session : record;
  const status = mapSessionStatus(nestedSession.status ?? record.status);
  const candidateSource =
    nestedSession.candidate ?? record.candidate ?? nestedSession;

  const questions = options.questions ?? [];
  const currentQuestion =
    options.currentQuestion ??
    (isRecord(nestedSession.question)
      ? mapInterviewQuestion(nestedSession.question)
      : null) ??
    questions[0] ??
    emptyQuestion();

  const progressPercent = asNumber(
    nestedSession.progress_percent ??
      nestedSession.progressPercent ??
      nestedSession.progress,
    currentQuestion.total > 0
      ? Math.round((currentQuestion.index / currentQuestion.total) * 100)
      : 0
  );

  return {
    id: asString(nestedSession.id ?? record.id),
    status,
    phase: mapPhaseFromStatus(status),
    candidate: mapCandidate(candidateSource),
    question: currentQuestion,
    progressPercent,
    estimatedRemainingLabel: asString(
      nestedSession.estimated_remaining_label ??
        nestedSession.estimatedRemainingLabel,
      "—"
    ),
    latencyMs: asNumber(nestedSession.latency_ms ?? nestedSession.latencyMs),
    isMuted: Boolean(nestedSession.is_muted ?? nestedSession.isMuted),
    isCameraOn: Boolean(
      nestedSession.is_camera_on ?? nestedSession.isCameraOn ?? true
    ),
    isScreenShareEnabled: Boolean(
      nestedSession.is_screen_share_enabled ??
        nestedSession.isScreenShareEnabled
    ),
    isAiThinking: Boolean(
      nestedSession.is_ai_thinking ?? nestedSession.isAiThinking
    ),
    isCandidateSpeaking: Boolean(
      nestedSession.is_candidate_speaking ?? nestedSession.isCandidateSpeaking
    ),
    speakingSpeedWpm: asNumber(
      nestedSession.speaking_speed_wpm ?? nestedSession.speakingSpeedWpm
    ),
    sentiment: (() => {
      const sentiment = asString(
        nestedSession.sentiment,
        "neutral"
      ).toLowerCase();
      if (sentiment === "positive" || sentiment === "cautious") {
        return sentiment;
      }
      return "neutral";
    })(),
    aiNotes: asString(nestedSession.ai_notes ?? nestedSession.aiNotes),
    transcript: options.transcript ?? mapTranscriptPayload(nestedSession.transcript),
    metrics: mapMetrics(nestedSession.metrics),
    metricSeries: mapMetricSeries(
      nestedSession.metric_series ?? nestedSession.metricSeries
    ),
    agents: mapAgents(nestedSession.agents),
  };
}

export function mapStartInterviewResponse(
  dto: unknown
): StartInterviewResponse {
  return {
    session: mapInterviewRoomSession(dto),
  };
}

export function mapEndInterviewResponse(dto: unknown): EndInterviewResponse {
  const record = isRecord(dto) ? dto : {};
  return {
    interviewId: asString(record.interview_id ?? record.interviewId ?? record.id),
    status: "ended",
    endedAt: asString(record.ended_at ?? record.endedAt, new Date().toISOString()),
  };
}

export function mergeRoomSession(options: {
  interview: InterviewRoomSession;
  questionsPayload?: unknown;
  transcriptPayload?: unknown;
}): InterviewRoomSession {
  const mappedQuestions = options.questionsPayload
    ? mapQuestionsPayload(options.questionsPayload)
    : null;
  const transcript = options.transcriptPayload
    ? mapTranscriptPayload(options.transcriptPayload)
    : options.interview.transcript;

  return {
    ...options.interview,
    question:
      mappedQuestions?.currentQuestion ?? options.interview.question,
    progressPercent:
      mappedQuestions && mappedQuestions.currentQuestion
        ? Math.round(
            (mappedQuestions.currentQuestion.index /
              Math.max(mappedQuestions.currentQuestion.total, 1)) *
              100
          )
        : options.interview.progressPercent,
    transcript,
  };
}
