export type AgentRuntimeStatus =
  | "idle"
  | "running"
  | "busy"
  | "waiting"
  | "error"
  | "completed";

export type HealthStatus = "operational" | "warning" | "offline";

export type TimelinePhase = "done" | "active" | "waiting";

export type LogLevel = "info" | "success" | "pending" | "retry" | "error";

export type WorkflowNodeId =
  | "resume"
  | "planner"
  | "technical"
  | "behavior"
  | "factChecker"
  | "evaluation"
  | "hiring";

export interface AgentCardData {
  id: WorkflowNodeId;
  name: string;
  status: AgentRuntimeStatus;
  currentTask: string;
  executionTimeMs: number;
  queueSize: number;
  memoryMb: number;
  cpuPercent: number;
  successRate: number;
  confidence: number;
  lastUpdated: string;
}

export interface SystemServiceHealth {
  id: string;
  name: string;
  status: HealthStatus;
  detail: string;
}

export interface WorkflowNode {
  id: WorkflowNodeId;
  label: string;
  status: AgentRuntimeStatus;
}

export interface TimelineLane {
  id: string;
  label: string;
  start: number;
  end: number;
  phase: TimelinePhase;
}

export interface LatencyPoint {
  time: string;
  latencyMs: number;
}

export interface ResourceSeriesPoint {
  time: string;
  cpu: number;
  memory: number;
  rpm: number;
  successRate: number;
}

export interface AgentCommunicationEdge {
  from: string;
  to: string;
  trafficPercent: number;
}

export interface ExecutionLogEntry {
  id: string;
  timestamp: string;
  agent: string;
  action: string;
  status: LogLevel;
  latencyMs: number;
}

export interface GlobalHealth {
  score: number;
  loadPercent: number;
  latencyMs: number;
}

export interface SessionStats {
  uptime: string;
  agentCycles: number;
  tasksResolved: number;
  activeSessions: number;
  totalActiveAgents: number;
  currentWorkflow: string;
}

export interface ResourceSaturation {
  cpuPercent: number;
  memoryPercent: number;
  networkGbps: number;
}

export interface AgentsOverview {
  monitorId: string;
  isLive: boolean;
  globalHealth: GlobalHealth;
  session: SessionStats;
  agents: ReadonlyArray<AgentCardData>;
  workflow: ReadonlyArray<WorkflowNode>;
  activeNodeId: WorkflowNodeId;
  timeline: ReadonlyArray<TimelineLane>;
  latencySeries: ReadonlyArray<LatencyPoint>;
  resourceSeries: ReadonlyArray<ResourceSeriesPoint>;
  communication: ReadonlyArray<AgentCommunicationEdge>;
  systemHealth: ReadonlyArray<SystemServiceHealth>;
  resources: ResourceSaturation;
  avgLatencyMs: number;
  p99LatencyMs: number;
  clusterNodes: number;
  shard: string;
  optimizationHint: string;
  engineVersion: string;
  infrastructure: string;
  region: string;
  lastSyncedAt: string;
}

export interface AgentsStatusResponse {
  isLive: boolean;
  activeNodeId: WorkflowNodeId;
  agents: ReadonlyArray<Pick<AgentCardData, "id" | "status" | "currentTask">>;
}

export interface AgentsLogsResponse {
  logs: ReadonlyArray<ExecutionLogEntry>;
}

export interface AgentsMetricsResponse {
  latencySeries: ReadonlyArray<LatencyPoint>;
  resourceSeries: ReadonlyArray<ResourceSeriesPoint>;
  resources: ResourceSaturation;
  avgLatencyMs: number;
  p99LatencyMs: number;
}
