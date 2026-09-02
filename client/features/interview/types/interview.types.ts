export type InterviewType = "technical" | "behavioral" | "mixed";
export type InterviewDifficulty = "easy" | "medium" | "hard" | "extreme";
export type AgentStatus = "idle" | "running" | "ready" | "blocked";
export type WorkflowStepStatus = "completed" | "active" | "pending";

export interface PlanningCandidate {
  id: string;
  fullName: string;
  email: string;
  title: string;
  level: string;
  percentileLabel: string;
  avatarInitials: string;
  resumeScore: number;
  readinessScore: number;
  selectedRole: string;
  resumeId: string | null;
  resumeFileName: string | null;
  resumeStatus: string;
  resumeUploadedAt: string | null;
}

export interface InterviewConfiguration {
  role: string;
  difficulty: InterviewDifficulty;
  durationMinutes: number;
  questionCount: number;
  interviewType: InterviewType;
}

export interface InterviewAgent {
  id: string;
  name: string;
  description: string;
  status: AgentStatus;
  progress: number;
  ready: boolean;
}

export interface WorkflowStep {
  id: string;
  step: string;
  title: string;
  status: WorkflowStepStatus;
  icon: "resume" | "planning" | "questions" | "difficulty" | "graph" | "ready";
}

export interface ChecklistItem {
  id: string;
  label: string;
  completed: boolean;
}

export interface MetricBar {
  label: string;
  value: number;
}

export interface CoveragePoint {
  label: string;
  coverage: number;
}

export interface PlanningInsight {
  suggestions: ReadonlyArray<string>;
  strengths: ReadonlyArray<MetricBar>;
  gaps: ReadonlyArray<MetricBar>;
  strategy: string;
  recommendation: string;
}

export interface PlanningSummary {
  estimatedDurationMinutes: number;
  expectedQuestionCount: number;
  skillCoverage: number;
  confidenceScore: number;
  planningProgress: number;
  engineStatus: string;
  difficulty: InterviewDifficulty;
  skillsToCover: ReadonlyArray<string>;
}

export interface InterviewPlan {
  id: string;
  candidate: PlanningCandidate;
  configuration: InterviewConfiguration;
  agents: ReadonlyArray<InterviewAgent>;
  workflow: ReadonlyArray<WorkflowStep>;
  checklist: ReadonlyArray<ChecklistItem>;
  summary: PlanningSummary;
  skillDistribution: ReadonlyArray<MetricBar>;
  interviewCoverage: ReadonlyArray<CoveragePoint>;
  insights: PlanningInsight;
}

export interface CreateInterviewRequest {
  candidateId: string;
  resumeId: string;
  configuration: InterviewConfiguration;
}

export interface CreateInterviewResponse {
  interviewId: string;
  status: "created" | "queued";
}

export interface PlanInterviewRequest {
  candidateId: string;
  resumeId: string;
  configuration: InterviewConfiguration;
}

export interface PlanInterviewResponse {
  plan: InterviewPlan;
}

export type RoomAgentStatus = "active" | "waiting" | "completed";
export type InterviewRoomPhase =
  | "loading"
  | "live"
  | "ended"
  | "cancelled"
  | "connection_lost"
  | "microphone_denied"
  | "camera_denied";

export type TranscriptSpeaker = "ai" | "candidate";

export interface InterviewRoomCandidate {
  id: string;
  fullName: string;
  shortName: string;
  title: string;
  level: string;
  skills: ReadonlyArray<string>;
  avatarInitials: string;
}

export interface InterviewQuestion {
  id: string;
  index: number;
  total: number;
  topic: string;
  difficulty: InterviewDifficulty;
  prompt: string;
  evaluatorNotes: string;
  elapsedSeconds: number;
}

export interface TranscriptEntry {
  id: string;
  speaker: TranscriptSpeaker;
  speakerLabel: string;
  timestamp: string;
  content: string;
  accuracy?: number;
}

export interface LiveMetric {
  id: string;
  label: string;
  score: number;
  delta: number;
  icon: "technical" | "communication" | "confidence" | "leadership" | "quality";
}

export interface LiveMetricPoint {
  time: string;
  confidence: number;
  communication: number;
  technical: number;
}

export interface RoomAgent {
  id: string;
  name: string;
  status: RoomAgentStatus;
  progress: number;
  currentTask: string;
}

export interface InterviewRoomSession {
  id: string;
  status: "scheduled" | "live" | "ended" | "cancelled";
  phase: InterviewRoomPhase;
  candidate: InterviewRoomCandidate;
  question: InterviewQuestion;
  progressPercent: number;
  estimatedRemainingLabel: string;
  latencyMs: number;
  isMuted: boolean;
  isCameraOn: boolean;
  isScreenShareEnabled: boolean;
  isAiThinking: boolean;
  isCandidateSpeaking: boolean;
  speakingSpeedWpm: number;
  sentiment: "positive" | "neutral" | "cautious";
  aiNotes: string;
  transcript: ReadonlyArray<TranscriptEntry>;
  metrics: ReadonlyArray<LiveMetric>;
  metricSeries: ReadonlyArray<LiveMetricPoint>;
  agents: ReadonlyArray<RoomAgent>;
}

export interface StartInterviewRequest {
  interviewId: string;
}

export interface StartInterviewResponse {
  session: InterviewRoomSession;
}

export interface EndInterviewRequest {
  interviewId: string;
  reason?: "manual" | "completed" | "connection_lost";
}

export interface EndInterviewResponse {
  interviewId: string;
  status: "ended";
  endedAt: string;
}
