import type {
  AgentCardData,
  AgentRuntimeStatus,
  WorkflowNodeId,
} from "@/features/agents/types/agents.types";
import type {
  InterviewQuestion,
  LiveMetric,
  RoomAgent,
  TranscriptEntry,
} from "@/features/interview/types/interview.types";

export const SOCKET_EVENTS = {
  connect: "connect",
  disconnect: "disconnect",
  reconnect: "reconnect",
  reconnectAttempt: "reconnect_attempt",
  connectError: "connect_error",
  ping: "ping",
  pong: "pong",
  heartbeat: "heartbeat",
  authenticate: "authenticate",
  authenticated: "authenticated",
  authError: "auth_error",
  interviewStarted: "interview:started",
  interviewEnded: "interview:ended",
  questionChanged: "interview:question_changed",
  transcriptUpdated: "transcript:updated",
  aiThinking: "interview:ai_thinking",
  aiResponse: "interview:ai_response",
  candidateSpeaking: "interview:speaking",
  agentStatusUpdated: "agent:status_updated",
  evaluationUpdated: "interview:evaluation_updated",
  progressUpdated: "interview:progress_updated",
  notification: "system:notification",
  systemError: "system:error",
  joinInterview: "interview:join",
  leaveInterview: "interview:leave",
  joinAgents: "agents:join",
  leaveAgents: "agents:leave",
} as const;

export type SocketEventName =
  (typeof SOCKET_EVENTS)[keyof typeof SOCKET_EVENTS];

export type SocketConnectionStatus =
  | "idle"
  | "connecting"
  | "connected"
  | "reconnecting"
  | "disconnected"
  | "auth_failed"
  | "error";

export interface SocketNotificationPayload {
  id: string;
  title: string;
  message: string;
  level: "info" | "warning" | "error" | "success";
  at: string;
}

export interface SocketSystemErrorPayload {
  code: string | null;
  message: string;
  retryable: boolean;
  at: string;
}

export interface InterviewStartedPayload {
  interviewId: string;
  startedAt: string;
}

export interface InterviewEndedPayload {
  interviewId: string;
  endedAt: string;
  reason?: "manual" | "completed" | "connection_lost" | "cancelled";
}

export interface QuestionChangedPayload {
  interviewId: string;
  question: InterviewQuestion;
}

export interface TranscriptUpdatedPayload {
  interviewId: string;
  entry: TranscriptEntry;
}

export interface AiThinkingPayload {
  interviewId: string;
  isThinking: boolean;
}

export interface AiResponsePayload {
  interviewId: string;
  content: string;
  at: string;
}

export interface AgentStatusUpdatedPayload {
  agentId: WorkflowNodeId | string;
  status: AgentRuntimeStatus | RoomAgent["status"];
  currentTask: string;
  cpuPercent?: number;
  memoryMb?: number;
  agent?: Partial<AgentCardData> | Partial<RoomAgent>;
}

export interface EvaluationUpdatedPayload {
  interviewId: string;
  metrics: ReadonlyArray<LiveMetric>;
  latencyMs?: number;
}

export interface ProgressUpdatedPayload {
  interviewId: string;
  progressPercent: number;
  estimatedRemainingLabel?: string;
  questionIndex?: number;
  questionTotal?: number;
}

export interface InterviewSpeakingPayload {
  interviewId?: string;
  isSpeaking: boolean;
}

export type SocketPayloadMap = {
  [SOCKET_EVENTS.connect]: { at: string };
  [SOCKET_EVENTS.disconnect]: { at: string; reason?: string };
  [SOCKET_EVENTS.reconnect]: { at: string; attempt: number };
  [SOCKET_EVENTS.reconnectAttempt]: { at: string; attempt: number };
  [SOCKET_EVENTS.connectError]: { at: string; message: string };
  [SOCKET_EVENTS.ping]: { at: string };
  [SOCKET_EVENTS.pong]: { at: string; latencyMs: number };
  [SOCKET_EVENTS.heartbeat]: { at: string };
  [SOCKET_EVENTS.authenticate]: { token: string };
  [SOCKET_EVENTS.authenticated]: { at: string };
  [SOCKET_EVENTS.authError]: { at: string; message: string };
  [SOCKET_EVENTS.interviewStarted]: InterviewStartedPayload;
  [SOCKET_EVENTS.interviewEnded]: InterviewEndedPayload;
  [SOCKET_EVENTS.questionChanged]: QuestionChangedPayload;
  [SOCKET_EVENTS.transcriptUpdated]: TranscriptUpdatedPayload;
  [SOCKET_EVENTS.aiThinking]: AiThinkingPayload;
  [SOCKET_EVENTS.aiResponse]: AiResponsePayload;
  [SOCKET_EVENTS.candidateSpeaking]: InterviewSpeakingPayload;
  [SOCKET_EVENTS.agentStatusUpdated]: AgentStatusUpdatedPayload;
  [SOCKET_EVENTS.evaluationUpdated]: EvaluationUpdatedPayload;
  [SOCKET_EVENTS.progressUpdated]: ProgressUpdatedPayload;
  [SOCKET_EVENTS.notification]: SocketNotificationPayload;
  [SOCKET_EVENTS.systemError]: SocketSystemErrorPayload;
  [SOCKET_EVENTS.joinInterview]: { interviewId: string };
  [SOCKET_EVENTS.leaveInterview]: { interviewId: string };
  [SOCKET_EVENTS.joinAgents]: { at: string };
  [SOCKET_EVENTS.leaveAgents]: { at: string };
};

/** Backward-compatible interview event aliases used by existing room hooks. */
export const INTERVIEW_SOCKET_EVENTS = {
  connect: SOCKET_EVENTS.connect,
  disconnect: SOCKET_EVENTS.disconnect,
  join: SOCKET_EVENTS.joinInterview,
  leave: SOCKET_EVENTS.leaveInterview,
  transcript: SOCKET_EVENTS.transcriptUpdated,
  metrics: SOCKET_EVENTS.evaluationUpdated,
  thinking: SOCKET_EVENTS.aiThinking,
  speaking: SOCKET_EVENTS.candidateSpeaking,
  question: SOCKET_EVENTS.questionChanged,
  heartbeat: SOCKET_EVENTS.heartbeat,
  error: SOCKET_EVENTS.systemError,
} as const;

export type InterviewSocketEvent =
  (typeof INTERVIEW_SOCKET_EVENTS)[keyof typeof INTERVIEW_SOCKET_EVENTS];

export type InterviewSocketPayloadMap = SocketPayloadMap;
