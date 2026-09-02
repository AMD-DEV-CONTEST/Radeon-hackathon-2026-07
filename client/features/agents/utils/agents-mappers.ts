import type {
  AgentCardData,
  AgentCommunicationEdge,
  AgentRuntimeStatus,
  AgentsLogsResponse,
  AgentsMetricsResponse,
  AgentsOverview,
  AgentsStatusResponse,
  ExecutionLogEntry,
  GlobalHealth,
  HealthStatus,
  LatencyPoint,
  LogLevel,
  ResourceSaturation,
  ResourceSeriesPoint,
  SessionStats,
  SystemServiceHealth,
  TimelineLane,
  TimelinePhase,
  WorkflowNode,
  WorkflowNodeId,
} from "@/features/agents/types/agents.types";

const WORKFLOW_NODE_IDS: ReadonlyArray<WorkflowNodeId> = [
  "resume",
  "planner",
  "technical",
  "behavior",
  "factChecker",
  "evaluation",
  "hiring",
];

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
  if (isRecord(payload) && Array.isArray(payload.agents)) {
    return payload.agents;
  }
  if (isRecord(payload) && Array.isArray(payload.logs)) {
    return payload.logs;
  }
  if (isRecord(payload) && Array.isArray(payload.services)) {
    return payload.services;
  }
  if (isRecord(payload) && Array.isArray(payload.nodes)) {
    return payload.nodes;
  }
  if (isRecord(payload) && Array.isArray(payload.timeline)) {
    return payload.timeline;
  }
  return [];
}

function mapWorkflowNodeId(value: unknown, fallback: WorkflowNodeId = "planner"): WorkflowNodeId {
  const normalized = asString(value)
    .toLowerCase()
    .replace(/[\s_-]+/g, "");

  if (normalized === "resume" || normalized === "resumeagent") {
    return "resume";
  }
  if (normalized === "planner" || normalized === "planneragent") {
    return "planner";
  }
  if (normalized === "technical" || normalized === "technicalagent") {
    return "technical";
  }
  if (
    normalized === "behavior" ||
    normalized === "behavioral" ||
    normalized === "behavioragent"
  ) {
    return "behavior";
  }
  if (
    normalized === "factchecker" ||
    normalized === "fact" ||
    normalized === "checker"
  ) {
    return "factChecker";
  }
  if (normalized === "evaluation" || normalized === "eval") {
    return "evaluation";
  }
  if (normalized === "hiring" || normalized === "hire") {
    return "hiring";
  }

  return fallback;
}

function mapRuntimeStatus(value: unknown): AgentRuntimeStatus {
  const normalized = asString(value).toLowerCase();
  if (
    normalized === "idle" ||
    normalized === "running" ||
    normalized === "busy" ||
    normalized === "waiting" ||
    normalized === "error" ||
    normalized === "completed"
  ) {
    return normalized;
  }
  if (normalized === "active" || normalized === "processing") {
    return "running";
  }
  if (normalized === "done" || normalized === "success") {
    return "completed";
  }
  if (normalized === "failed" || normalized === "down") {
    return "error";
  }
  if (normalized === "queued" || normalized === "standby") {
    return "waiting";
  }
  return "idle";
}

function mapHealthStatus(value: unknown): HealthStatus {
  const normalized = asString(value).toLowerCase();
  if (normalized === "warning" || normalized === "degraded") {
    return "warning";
  }
  if (normalized === "offline" || normalized === "down" || normalized === "critical") {
    return "offline";
  }
  return "operational";
}

function mapTimelinePhase(value: unknown): TimelinePhase {
  const normalized = asString(value).toLowerCase();
  if (normalized === "done" || normalized === "completed") {
    return "done";
  }
  if (normalized === "active" || normalized === "running") {
    return "active";
  }
  return "waiting";
}

function mapLogLevel(value: unknown): LogLevel {
  const normalized = asString(value).toLowerCase();
  if (
    normalized === "info" ||
    normalized === "success" ||
    normalized === "pending" ||
    normalized === "retry" ||
    normalized === "error"
  ) {
    return normalized;
  }
  if (normalized === "warn" || normalized === "warning") {
    return "retry";
  }
  if (normalized === "ok" || normalized === "done") {
    return "success";
  }
  return "info";
}

function mapGlobalHealth(value: unknown): GlobalHealth {
  const record = isRecord(value) ? value : {};
  return {
    score: asNumber(record.score ?? record.health ?? record.value, 100),
    loadPercent: asNumber(record.load_percent ?? record.loadPercent ?? record.load),
    latencyMs: asNumber(record.latency_ms ?? record.latencyMs ?? record.latency),
  };
}

function mapSession(value: unknown): SessionStats {
  const record = isRecord(value) ? value : {};
  return {
    uptime: asString(record.uptime, "00:00:00"),
    agentCycles: asNumber(record.agent_cycles ?? record.agentCycles),
    tasksResolved: asNumber(record.tasks_resolved ?? record.tasksResolved),
    activeSessions: asNumber(record.active_sessions ?? record.activeSessions),
    totalActiveAgents: asNumber(
      record.total_active_agents ?? record.totalActiveAgents
    ),
    currentWorkflow: asString(
      record.current_workflow ?? record.currentWorkflow,
      "Interview Orchestration"
    ),
  };
}

function mapAgentCard(value: unknown, index: number): AgentCardData | null {
  if (!isRecord(value)) {
    return null;
  }

  const name = asString(value.name ?? value.agent ?? value.label).trim();
  if (!name && !value.id) {
    return null;
  }

  const fallbackId = WORKFLOW_NODE_IDS[index] ?? "planner";

  return {
    id: mapWorkflowNodeId(value.id ?? value.key ?? name, fallbackId),
    name: name || asString(value.id, "Agent"),
    status: mapRuntimeStatus(value.status),
    currentTask: asString(
      value.current_task ?? value.currentTask ?? value.task
    ),
    executionTimeMs: asNumber(
      value.execution_time_ms ?? value.executionTimeMs ?? value.latency_ms
    ),
    queueSize: asNumber(value.queue_size ?? value.queueSize ?? value.queue),
    memoryMb: asNumber(value.memory_mb ?? value.memoryMb ?? value.memory),
    cpuPercent: asNumber(value.cpu_percent ?? value.cpuPercent ?? value.cpu),
    successRate: asNumber(
      value.success_rate ?? value.successRate,
      100
    ),
    confidence: asNumber(value.confidence ?? value.confidence_score),
    lastUpdated: asString(
      value.last_updated ?? value.lastUpdated ?? value.updated_at,
      "—"
    ),
  };
}

function mapAgents(value: unknown): AgentCardData[] {
  return compactMap(unwrapItems(value).map((item, index) => mapAgentCard(item, index)));
}

function mapWorkflow(value: unknown, agents: ReadonlyArray<AgentCardData>): WorkflowNode[] {
  const mapped = compactMap(
    unwrapItems(value).map((item, index) => {
      if (!isRecord(item)) {
        return null;
      }
      const fallbackId = WORKFLOW_NODE_IDS[index] ?? "planner";
      const id = mapWorkflowNodeId(item.id ?? item.key ?? item.name, fallbackId);
      return {
        id,
        label: asString(item.label ?? item.name, id),
        status: mapRuntimeStatus(item.status),
      };
    })
  );

  if (mapped.length > 0) {
    return mapped;
  }

  return agents.map((agent) => ({
    id: agent.id,
    label: agent.name,
    status: agent.status,
  }));
}

function mapTimeline(value: unknown): TimelineLane[] {
  return compactMap(
    unwrapItems(value).map((item, index) => {
      if (!isRecord(item)) {
        return null;
      }
      const label = asString(item.label ?? item.name ?? item.agent).trim();
      if (!label) {
        return null;
      }
      return {
        id: asString(item.id, `lane-${index + 1}`),
        label,
        start: asNumber(item.start ?? item.start_minute ?? item.from),
        end: asNumber(item.end ?? item.end_minute ?? item.to),
        phase: mapTimelinePhase(item.phase ?? item.status),
      };
    })
  );
}

function mapLatencySeries(value: unknown): LatencyPoint[] {
  return compactMap(
    unwrapItems(value).map((item) => {
      if (!isRecord(item)) {
        return null;
      }
      const time = asString(item.time ?? item.label ?? item.t).trim();
      if (!time) {
        return null;
      }
      return {
        time,
        latencyMs: asNumber(item.latency_ms ?? item.latencyMs ?? item.latency),
      };
    })
  );
}

function mapResourceSeries(value: unknown): ResourceSeriesPoint[] {
  return compactMap(
    unwrapItems(value).map((item) => {
      if (!isRecord(item)) {
        return null;
      }
      const time = asString(item.time ?? item.label ?? item.t).trim();
      if (!time) {
        return null;
      }
      return {
        time,
        cpu: asNumber(item.cpu ?? item.cpu_percent),
        memory: asNumber(item.memory ?? item.memory_percent),
        rpm: asNumber(item.rpm ?? item.requests_per_minute),
        successRate: asNumber(
          item.success_rate ?? item.successRate,
          100
        ),
      };
    })
  );
}

function mapCommunication(value: unknown): AgentCommunicationEdge[] {
  return compactMap(
    unwrapItems(value).map((item) => {
      if (!isRecord(item)) {
        return null;
      }
      const from = asString(item.from ?? item.source).trim();
      const to = asString(item.to ?? item.target).trim();
      if (!from || !to) {
        return null;
      }
      return {
        from,
        to,
        trafficPercent: asNumber(
          item.traffic_percent ?? item.trafficPercent ?? item.traffic
        ),
      };
    })
  );
}

function mapSystemHealth(value: unknown): SystemServiceHealth[] {
  return compactMap(
    unwrapItems(value).map((item, index) => {
      if (!isRecord(item)) {
        return null;
      }
      const name = asString(item.name ?? item.service ?? item.label).trim();
      if (!name) {
        return null;
      }
      return {
        id: asString(item.id, `service-${index + 1}`),
        name,
        status: mapHealthStatus(item.status),
        detail: asString(item.detail ?? item.message ?? item.description),
      };
    })
  );
}

function mapResources(value: unknown): ResourceSaturation {
  const record = isRecord(value) ? value : {};
  return {
    cpuPercent: asNumber(record.cpu_percent ?? record.cpuPercent ?? record.cpu),
    memoryPercent: asNumber(
      record.memory_percent ?? record.memoryPercent ?? record.memory
    ),
    networkGbps: asNumber(
      record.network_gbps ?? record.networkGbps ?? record.network
    ),
  };
}

function mapLogs(value: unknown): ExecutionLogEntry[] {
  return compactMap(
    unwrapItems(value).map((item, index) => {
      if (!isRecord(item)) {
        return null;
      }
      const action = asString(
        item.action ?? item.message ?? item.event ?? item.detail
      ).trim();
      if (!action) {
        return null;
      }
      return {
        id: asString(item.id, `log-${index + 1}`),
        timestamp: asString(
          item.timestamp ?? item.time ?? item.created_at
        ),
        agent: asString(item.agent ?? item.agent_name ?? item.source),
        action,
        status: mapLogLevel(item.status ?? item.level),
        latencyMs: asNumber(item.latency_ms ?? item.latencyMs ?? item.latency),
      };
    })
  );
}

export function mapAgentsOverview(dto: unknown): AgentsOverview {
  const record = isRecord(dto) ? dto : {};
  const nested = isRecord(record.overview)
    ? record.overview
    : isRecord(record.monitor)
      ? record.monitor
      : record;

  const agents = mapAgents(nested.agents ?? nested.agent_cards);
  const activeNodeId = mapWorkflowNodeId(
    nested.active_node_id ?? nested.activeNodeId ?? nested.active_node,
    agents.find((agent) => agent.status === "running" || agent.status === "busy")
      ?.id ?? "planner"
  );

  return {
    monitorId: asString(nested.monitor_id ?? nested.monitorId ?? nested.id),
    isLive: Boolean(nested.is_live ?? nested.isLive ?? true),
    globalHealth: mapGlobalHealth(
      nested.global_health ?? nested.globalHealth ?? nested.health
    ),
    session: mapSession(nested.session ?? nested.session_stats ?? nested),
    agents,
    workflow: mapWorkflow(nested.workflow ?? nested.nodes, agents),
    activeNodeId,
    timeline: mapTimeline(nested.timeline ?? nested.execution_timeline),
    latencySeries: mapLatencySeries(
      nested.latency_series ?? nested.latencySeries ?? nested.latency
    ),
    resourceSeries: mapResourceSeries(
      nested.resource_series ?? nested.resourceSeries ?? nested.resources_series
    ),
    communication: mapCommunication(
      nested.communication ?? nested.edges ?? nested.traffic
    ),
    systemHealth: mapSystemHealth(
      nested.system_health ?? nested.systemHealth ?? nested.services
    ),
    resources: mapResources(nested.resources ?? nested.resource_saturation),
    avgLatencyMs: asNumber(
      nested.avg_latency_ms ?? nested.avgLatencyMs ?? nested.average_latency
    ),
    p99LatencyMs: asNumber(
      nested.p99_latency_ms ?? nested.p99LatencyMs ?? nested.p99
    ),
    clusterNodes: asNumber(
      nested.cluster_nodes ?? nested.clusterNodes ?? nested.nodes_count
    ),
    shard: asString(nested.shard, "—"),
    optimizationHint: asString(
      nested.optimization_hint ?? nested.optimizationHint
    ),
    engineVersion: asString(
      nested.engine_version ?? nested.engineVersion,
      "AgentVox Monitor"
    ),
    infrastructure: asString(
      nested.infrastructure ?? nested.infra,
      "—"
    ),
    region: asString(nested.region, "—"),
    lastSyncedAt: asString(
      nested.last_synced_at ?? nested.lastSyncedAt ?? nested.updated_at,
      new Date().toISOString()
    ),
  };
}

export function mapAgentsStatus(dto: unknown): AgentsStatusResponse {
  const record = isRecord(dto) ? dto : {};
  const agents = compactMap(
    unwrapItems(record.agents ?? dto).map((item, index) => {
      const card = mapAgentCard(item, index);
      if (!card) {
        return null;
      }
      return {
        id: card.id,
        status: card.status,
        currentTask: card.currentTask,
      };
    })
  );

  return {
    isLive: Boolean(record.is_live ?? record.isLive ?? true),
    activeNodeId: mapWorkflowNodeId(
      record.active_node_id ?? record.activeNodeId,
      agents[0]?.id ?? "planner"
    ),
    agents,
  };
}

export function mapAgentsLogs(dto: unknown): AgentsLogsResponse {
  const record = isRecord(dto) ? dto : {};
  return {
    logs: mapLogs(record.logs ?? dto),
  };
}

export function mapAgentsMetrics(dto: unknown): AgentsMetricsResponse {
  const record = isRecord(dto) ? dto : {};
  const nested = isRecord(record.metrics) ? record.metrics : record;

  return {
    latencySeries: mapLatencySeries(
      nested.latency_series ?? nested.latencySeries ?? nested.latency
    ),
    resourceSeries: mapResourceSeries(
      nested.resource_series ?? nested.resourceSeries
    ),
    resources: mapResources(nested.resources ?? nested.resource_saturation),
    avgLatencyMs: asNumber(
      nested.avg_latency_ms ?? nested.avgLatencyMs
    ),
    p99LatencyMs: asNumber(
      nested.p99_latency_ms ?? nested.p99LatencyMs
    ),
  };
}

export function mergeAgentsOverview(options: {
  overview: AgentsOverview;
  status?: AgentsStatusResponse | null;
  metrics?: AgentsMetricsResponse | null;
}): AgentsOverview {
  const { overview, status, metrics } = options;

  const agents = status?.agents.length
    ? overview.agents.map((agent) => {
        const live = status.agents.find((item) => item.id === agent.id);
        if (!live) {
          return agent;
        }
        return {
          ...agent,
          status: live.status,
          currentTask: live.currentTask || agent.currentTask,
        };
      })
    : overview.agents;

  return {
    ...overview,
    isLive: status?.isLive ?? overview.isLive,
    activeNodeId: status?.activeNodeId ?? overview.activeNodeId,
    agents,
    latencySeries: metrics?.latencySeries.length
      ? metrics.latencySeries
      : overview.latencySeries,
    resourceSeries: metrics?.resourceSeries.length
      ? metrics.resourceSeries
      : overview.resourceSeries,
    resources: metrics
      ? {
          cpuPercent:
            metrics.resources.cpuPercent || overview.resources.cpuPercent,
          memoryPercent:
            metrics.resources.memoryPercent || overview.resources.memoryPercent,
          networkGbps:
            metrics.resources.networkGbps || overview.resources.networkGbps,
        }
      : overview.resources,
    avgLatencyMs: metrics?.avgLatencyMs || overview.avgLatencyMs,
    p99LatencyMs: metrics?.p99LatencyMs || overview.p99LatencyMs,
  };
}
