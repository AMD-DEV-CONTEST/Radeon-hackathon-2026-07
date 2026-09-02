import type {
  ActiveAgentRow,
  AdminAnalytics,
  AdminDashboard,
  AdminInterviewsResponse,
  AdminKpi,
  AdminNotification,
  AdminNotificationKind,
  AdminQuickAction,
  AdminSystemResponse,
  AdminUsersResponse,
  AgentUsagePoint,
  AiReportItem,
  CandidatePipelineStatus,
  InterviewLiveStatus,
  InterviewStatistics,
  InterviewTrendPoint,
  LiveInterviewSession,
  PlatformOverview,
  PlatformUsagePoint,
  RecentCandidateRow,
  RecentInterviewRow,
  ServiceHealthStatus,
  SkillTrendPoint,
  StrategyInsights,
  SystemPerformancePoint,
  SystemServiceHealth,
  TalentFeedItem,
  UserGrowthPoint,
} from "@/features/admin/types/admin.types";

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
  if (isRecord(payload) && Array.isArray(payload.users)) {
    return payload.users;
  }
  if (isRecord(payload) && Array.isArray(payload.candidates)) {
    return payload.candidates;
  }
  if (isRecord(payload) && Array.isArray(payload.sessions)) {
    return payload.sessions;
  }
  if (isRecord(payload) && Array.isArray(payload.interviews)) {
    return payload.interviews;
  }
  if (isRecord(payload) && Array.isArray(payload.services)) {
    return payload.services;
  }
  if (isRecord(payload) && Array.isArray(payload.agents)) {
    return payload.agents;
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

function mapHealthStatus(value: unknown): ServiceHealthStatus {
  const normalized = asString(value).toLowerCase();
  if (
    normalized === "warning" ||
    normalized === "degraded" ||
    normalized === "elevated"
  ) {
    return "warning";
  }
  if (
    normalized === "offline" ||
    normalized === "down" ||
    normalized === "critical"
  ) {
    return "offline";
  }
  return "operational";
}

function mapLiveStatus(value: unknown): InterviewLiveStatus {
  const normalized = asString(value).toLowerCase();
  if (normalized === "queued" || normalized === "scheduled") {
    return "queued";
  }
  if (normalized === "completed" || normalized === "ended") {
    return "completed";
  }
  return "live";
}

function mapCandidateStatus(value: unknown): CandidatePipelineStatus {
  const normalized = asString(value).toLowerCase();
  if (normalized === "hired") {
    return "hired";
  }
  if (normalized === "rejected" || normalized === "no_hire") {
    return "rejected";
  }
  if (normalized === "evaluated" || normalized === "completed") {
    return "evaluated";
  }
  if (normalized === "interviewing" || normalized === "live") {
    return "interviewing";
  }
  return "pending";
}

function mapKpiIcon(value: unknown): AdminKpi["icon"] {
  const normalized = asString(value).toLowerCase();
  if (
    normalized === "active" ||
    normalized === "score" ||
    normalized === "hire" ||
    normalized === "users" ||
    normalized === "agents"
  ) {
    return normalized;
  }
  return "interviews";
}

function mapOverview(value: unknown): PlatformOverview {
  const record = isRecord(value) ? value : {};
  return {
    totalUsers: asNumber(
      record.total_users ?? record.totalUsers ?? record.users
    ),
    activeCandidates: asNumber(
      record.active_candidates ?? record.activeCandidates
    ),
    activeInterviews: asNumber(
      record.active_interviews ?? record.activeInterviews
    ),
    aiAgentsRunning: asNumber(
      record.ai_agents_running ??
        record.aiAgentsRunning ??
        record.active_agents
    ),
    region: asString(record.region, "—"),
    globalHealthPercent: asNumber(
      record.global_health_percent ??
        record.globalHealthPercent ??
        record.health,
      100
    ),
  };
}

function mapStatistics(value: unknown): InterviewStatistics {
  const record = isRecord(value) ? value : {};
  return {
    daily: asNumber(record.daily ?? record.daily_interviews),
    weekly: asNumber(record.weekly ?? record.weekly_interviews),
    monthly: asNumber(record.monthly ?? record.monthly_interviews),
    averageScore: asNumber(
      record.average_score ?? record.averageScore ?? record.avg_score
    ),
    hiringSuccessRate: asNumber(
      record.hiring_success_rate ??
        record.hiringSuccessRate ??
        record.hire_rate
    ),
  };
}

function mapKpis(value: unknown, overview: PlatformOverview): AdminKpi[] {
  if (Array.isArray(value) && value.length > 0) {
    return compactMap(
      value.map((item, index) => {
        if (!isRecord(item)) {
          return null;
        }
        const label = asString(item.label ?? item.name).trim();
        if (!label) {
          return null;
        }
        return {
          id: asString(item.id, `kpi-${index + 1}`),
          label,
          value: asNumber(item.value ?? item.count),
          suffix: asString(item.suffix) || undefined,
          delta: asNumber(item.delta ?? item.change),
          icon: mapKpiIcon(item.icon ?? item.type),
        };
      })
    );
  }

  return [
    {
      id: "active-interviews",
      label: "Active Interviews",
      value: overview.activeInterviews,
      delta: 0,
      icon: "active",
    },
    {
      id: "active-candidates",
      label: "Active Candidates",
      value: overview.activeCandidates,
      delta: 0,
      icon: "users",
    },
    {
      id: "agents",
      label: "AI Agents Running",
      value: overview.aiAgentsRunning,
      delta: 0,
      icon: "agents",
    },
    {
      id: "health",
      label: "Platform Health",
      value: overview.globalHealthPercent,
      suffix: "%",
      delta: 0,
      icon: "score",
    },
  ];
}

function mapInterviewTrends(value: unknown): InterviewTrendPoint[] {
  return compactMap(
    unwrapItems(value).map((item) => {
      if (!isRecord(item)) {
        return null;
      }
      const label = asString(item.label ?? item.period ?? item.month).trim();
      if (!label) {
        return null;
      }
      return {
        label,
        volume: asNumber(item.volume ?? item.count ?? item.interviews),
        quality: asNumber(item.quality ?? item.score ?? item.avg_score),
      };
    })
  );
}

function mapUserGrowth(value: unknown): UserGrowthPoint[] {
  return compactMap(
    unwrapItems(value).map((item) => {
      if (!isRecord(item)) {
        return null;
      }
      const label = asString(item.label ?? item.period ?? item.month).trim();
      if (!label) {
        return null;
      }
      return {
        label,
        users: asNumber(item.users ?? item.count ?? item.value),
      };
    })
  );
}

function mapAgentUsage(value: unknown): AgentUsagePoint[] {
  return compactMap(
    unwrapItems(value).map((item) => {
      if (!isRecord(item)) {
        return null;
      }
      const label = asString(item.label ?? item.name ?? item.agent).trim();
      if (!label) {
        return null;
      }
      return {
        label,
        usage: asNumber(item.usage ?? item.percent ?? item.value),
      };
    })
  );
}

function mapPlatformUsage(value: unknown): PlatformUsagePoint[] {
  return compactMap(
    unwrapItems(value).map((item) => {
      if (!isRecord(item)) {
        return null;
      }
      const label = asString(item.label ?? item.day ?? item.period).trim();
      if (!label) {
        return null;
      }
      return {
        label,
        sessions: asNumber(item.sessions ?? item.count),
        apiCalls: asNumber(item.api_calls ?? item.apiCalls ?? item.calls),
      };
    })
  );
}

function mapSystemPerformance(value: unknown): SystemPerformancePoint[] {
  return compactMap(
    unwrapItems(value).map((item) => {
      if (!isRecord(item)) {
        return null;
      }
      const label = asString(item.label ?? item.time ?? item.t).trim();
      if (!label) {
        return null;
      }
      return {
        label,
        cpu: asNumber(item.cpu ?? item.cpu_percent),
        memory: asNumber(item.memory ?? item.memory_percent),
        latencyMs: asNumber(item.latency_ms ?? item.latencyMs ?? item.latency),
      };
    })
  );
}

function mapSkillTrends(value: unknown): SkillTrendPoint[] {
  return compactMap(
    unwrapItems(value).map((item) => {
      if (!isRecord(item)) {
        return null;
      }
      const skill = asString(item.skill ?? item.name ?? item.label).trim();
      if (!skill) {
        return null;
      }
      return {
        skill,
        demand: asNumber(item.demand ?? item.demand_score),
        supply: asNumber(item.supply ?? item.supply_score),
      };
    })
  );
}

function mapLiveSessions(value: unknown): LiveInterviewSession[] {
  return compactMap(
    unwrapItems(value).map((item, index) => {
      if (!isRecord(item)) {
        return null;
      }
      const candidateName = asString(
        item.candidate_name ?? item.candidateName ?? item.name
      ).trim();
      if (!candidateName) {
        return null;
      }
      return {
        id: asString(item.id, `session-${index + 1}`),
        candidateName,
        candidateInitials: asString(
          item.candidate_initials ?? item.candidateInitials,
          getInitials(candidateName)
        ),
        role: asString(item.role ?? item.title ?? item.position),
        score: asNumber(item.score ?? item.current_score),
        elapsed: asString(item.elapsed ?? item.duration_label ?? item.elapsed_label),
        status: mapLiveStatus(item.status),
      };
    })
  );
}

function mapRecentCandidates(value: unknown): RecentCandidateRow[] {
  return compactMap(
    unwrapItems(value).map((item, index) => {
      if (!isRecord(item)) {
        return null;
      }
      const name = asString(
        item.name ?? item.full_name ?? item.fullName
      ).trim();
      if (!name) {
        return null;
      }
      return {
        id: asString(item.id, `candidate-${index + 1}`),
        name,
        initials: asString(
          item.initials ?? item.avatar_initials,
          getInitials(name)
        ),
        position: asString(
          item.position ?? item.title ?? item.role ?? item.applied_role
        ),
        score: asNumber(item.score ?? item.overall_score),
        status: mapCandidateStatus(item.status ?? item.pipeline_status),
        reportId: asString(item.report_id ?? item.reportId),
      };
    })
  );
}

function mapRecentInterviews(value: unknown): RecentInterviewRow[] {
  return compactMap(
    unwrapItems(value).map((item, index) => {
      if (!isRecord(item)) {
        return null;
      }
      return {
        id: asString(item.id, `interview-${index + 1}`),
        candidateName: asString(
          item.candidate_name ?? item.candidateName ?? item.name
        ),
        interviewTitle: asString(
          item.interview_title ?? item.interviewTitle ?? item.title ?? item.role
        ),
        startedAt: asString(
          item.started_at ?? item.startedAt ?? item.created_at
        ),
        durationMinutes: asNumber(
          item.duration_minutes ?? item.durationMinutes ?? item.duration
        ),
        result: asString(item.result ?? item.recommendation ?? item.status),
      };
    })
  );
}

function mapActiveAgents(value: unknown): ActiveAgentRow[] {
  return compactMap(
    unwrapItems(value).map((item, index) => {
      if (!isRecord(item)) {
        return null;
      }
      const name = asString(item.name ?? item.agent ?? item.label).trim();
      if (!name) {
        return null;
      }
      const statusRaw = asString(item.status).toLowerCase();
      const status: ActiveAgentRow["status"] =
        statusRaw === "idle" || statusRaw === "standby" ? statusRaw : "busy";

      return {
        id: asString(item.id, `agent-${index + 1}`),
        name,
        task: asString(
          item.task ?? item.current_task ?? item.currentTask
        ),
        busyPercent: asNumber(
          item.busy_percent ?? item.busyPercent ?? item.cpu_percent
        ),
        status,
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

function mapTalentFeed(value: unknown): TalentFeedItem[] {
  return compactMap(
    unwrapItems(value).map((item, index) => {
      if (!isRecord(item)) {
        return null;
      }
      const name = asString(item.name ?? item.full_name).trim();
      if (!name) {
        return null;
      }
      return {
        id: asString(item.id, `talent-${index + 1}`),
        name,
        title: asString(item.title ?? item.role ?? item.position),
        initials: asString(item.initials, getInitials(name)),
        score: asNumber(item.score),
      };
    })
  );
}

function mapAiReports(value: unknown): AiReportItem[] {
  return compactMap(
    unwrapItems(value).map((item, index) => {
      if (!isRecord(item)) {
        return null;
      }
      const title = asString(item.title ?? item.name).trim();
      if (!title) {
        return null;
      }
      return {
        id: asString(item.id, `ai-report-${index + 1}`),
        title,
        category: asString(item.category ?? item.type),
        timestamp: asString(
          item.timestamp ?? item.created_at ?? item.createdAt
        ),
      };
    })
  );
}

function mapStrategy(value: unknown): StrategyInsights {
  const record = isRecord(value) ? value : {};
  const probes = Array.isArray(record.probes)
    ? record.probes.map((item) => asString(item)).filter(Boolean)
    : [];

  return {
    hotTopic: asString(record.hot_topic ?? record.hotTopic),
    probes,
    questionQuality: asNumber(
      record.question_quality ?? record.questionQuality
    ),
    aiConfidence: asNumber(record.ai_confidence ?? record.aiConfidence),
  };
}

function mapNotificationKind(value: unknown): AdminNotificationKind {
  const normalized = asString(value).toLowerCase();
  if (
    normalized === "failed_interview" ||
    normalized.includes("failed")
  ) {
    return "failed_interview";
  }
  if (normalized === "ai_warning" || normalized.includes("ai")) {
    return "ai_warning";
  }
  if (normalized === "registration" || normalized.includes("register")) {
    return "registration";
  }
  return "system";
}

function mapNotifications(value: unknown): AdminNotification[] {
  return compactMap(
    unwrapItems(value).map((item, index) => {
      if (!isRecord(item)) {
        return null;
      }
      const title = asString(item.title ?? item.name).trim();
      if (!title) {
        return null;
      }
      return {
        id: asString(item.id, `notification-${index + 1}`),
        kind: mapNotificationKind(item.kind ?? item.type),
        title,
        message: asString(item.message ?? item.description ?? item.detail),
        timestamp: asString(
          item.timestamp ?? item.created_at ?? item.createdAt
        ),
      };
    })
  );
}

function mapQuickActions(value: unknown): AdminQuickAction[] {
  return compactMap(
    unwrapItems(value).map((item, index) => {
      if (!isRecord(item)) {
        return null;
      }
      const label = asString(item.label ?? item.name).trim();
      if (!label) {
        return null;
      }
      return {
        id: asString(item.id, `action-${index + 1}`),
        label,
        href: asString(item.href ?? item.url, "/admin"),
        description: asString(item.description ?? item.detail),
      };
    })
  );
}

export function mapAdminDashboard(dto: unknown): AdminDashboard {
  const record = isRecord(dto) ? dto : {};
  const nested = isRecord(record.dashboard) ? record.dashboard : record;
  const overview = mapOverview(
    nested.overview ?? nested.stats ?? nested.platform ?? nested
  );

  return {
    overview,
    kpis: mapKpis(nested.kpis ?? nested.metrics, overview),
    statistics: mapStatistics(
      nested.statistics ?? nested.interview_statistics ?? nested
    ),
    interviewTrends: mapInterviewTrends(
      nested.interview_trends ?? nested.interviewTrends ?? nested.trends
    ),
    userGrowth: mapUserGrowth(nested.user_growth ?? nested.userGrowth),
    agentUsage: mapAgentUsage(nested.agent_usage ?? nested.agentUsage),
    platformUsage: mapPlatformUsage(
      nested.platform_usage ?? nested.platformUsage
    ),
    systemPerformance: mapSystemPerformance(
      nested.system_performance ?? nested.systemPerformance
    ),
    skillTrends: mapSkillTrends(nested.skill_trends ?? nested.skillTrends),
    liveSessions: mapLiveSessions(
      nested.live_sessions ?? nested.liveSessions ?? nested.active_interviews
    ),
    recentCandidates: mapRecentCandidates(
      nested.recent_candidates ?? nested.recentCandidates ?? nested.candidates
    ),
    recentInterviews: mapRecentInterviews(
      nested.recent_interviews ?? nested.recentInterviews
    ),
    activeAgents: mapActiveAgents(
      nested.active_agents ?? nested.activeAgents ?? nested.agents
    ),
    systemHealth: mapSystemHealth(
      nested.system_health ?? nested.systemHealth ?? nested.services
    ),
    talentFeed: mapTalentFeed(nested.talent_feed ?? nested.talentFeed),
    aiReports: mapAiReports(nested.ai_reports ?? nested.aiReports),
    strategy: mapStrategy(nested.strategy ?? nested.strategy_insights),
    notifications: mapNotifications(nested.notifications),
    quickActions: mapQuickActions(
      nested.quick_actions ?? nested.quickActions
    ),
    engineVersion: asString(
      nested.engine_version ?? nested.engineVersion,
      "AgentVox Admin"
    ),
    lastSyncedAt: asString(
      nested.last_synced_at ?? nested.lastSyncedAt ?? nested.updated_at,
      new Date().toISOString()
    ),
  };
}

export function mapAdminAnalytics(dto: unknown): AdminAnalytics {
  const record = isRecord(dto) ? dto : {};
  const nested = isRecord(record.analytics) ? record.analytics : record;

  return {
    statistics: mapStatistics(
      nested.statistics ?? nested.interview_statistics ?? nested
    ),
    interviewTrends: mapInterviewTrends(
      nested.interview_trends ?? nested.interviewTrends ?? nested.trends
    ),
    userGrowth: mapUserGrowth(nested.user_growth ?? nested.userGrowth),
    agentUsage: mapAgentUsage(nested.agent_usage ?? nested.agentUsage),
    platformUsage: mapPlatformUsage(
      nested.platform_usage ?? nested.platformUsage
    ),
    systemPerformance: mapSystemPerformance(
      nested.system_performance ?? nested.systemPerformance
    ),
  };
}

export function mapAdminUsers(dto: unknown): AdminUsersResponse {
  const record = isRecord(dto) ? dto : {};
  const users = mapRecentCandidates(
    record.users ?? record.candidates ?? record.items ?? dto
  );

  return {
    users,
    totalUsers: asNumber(record.total_users ?? record.totalUsers, users.length),
  };
}

export function mapAdminInterviews(dto: unknown): AdminInterviewsResponse {
  const record = isRecord(dto) ? dto : {};

  return {
    liveSessions: mapLiveSessions(
      record.live_sessions ??
        record.liveSessions ??
        record.active_interviews ??
        record.sessions
    ),
    recentInterviews: mapRecentInterviews(
      record.recent_interviews ?? record.recentInterviews ?? record.interviews
    ),
  };
}

export function mapAdminSystem(dto: unknown): AdminSystemResponse {
  const record = isRecord(dto) ? dto : {};

  return {
    services: mapSystemHealth(
      record.services ?? record.system_health ?? record.systemHealth
    ),
    activeAgents: mapActiveAgents(
      record.active_agents ?? record.activeAgents ?? record.agents
    ),
    globalHealthPercent: asNumber(
      record.global_health_percent ??
        record.globalHealthPercent ??
        record.health,
      100
    ),
  };
}

export function mergeAdminDashboard(options: {
  dashboard: AdminDashboard;
  analytics?: AdminAnalytics | null;
  users?: AdminUsersResponse | null;
  interviews?: AdminInterviewsResponse | null;
  system?: AdminSystemResponse | null;
}): AdminDashboard {
  const { dashboard, analytics, users, interviews, system } = options;

  return {
    ...dashboard,
    overview: {
      ...dashboard.overview,
      totalUsers: users?.totalUsers || dashboard.overview.totalUsers,
      globalHealthPercent:
        system?.globalHealthPercent || dashboard.overview.globalHealthPercent,
    },
    statistics: analytics?.statistics ?? dashboard.statistics,
    interviewTrends: analytics?.interviewTrends.length
      ? analytics.interviewTrends
      : dashboard.interviewTrends,
    userGrowth: analytics?.userGrowth.length
      ? analytics.userGrowth
      : dashboard.userGrowth,
    agentUsage: analytics?.agentUsage.length
      ? analytics.agentUsage
      : dashboard.agentUsage,
    platformUsage: analytics?.platformUsage.length
      ? analytics.platformUsage
      : dashboard.platformUsage,
    systemPerformance: analytics?.systemPerformance.length
      ? analytics.systemPerformance
      : dashboard.systemPerformance,
    recentCandidates: users?.users.length
      ? users.users
      : dashboard.recentCandidates,
    liveSessions: interviews?.liveSessions.length
      ? interviews.liveSessions
      : dashboard.liveSessions,
    recentInterviews: interviews?.recentInterviews.length
      ? interviews.recentInterviews
      : dashboard.recentInterviews,
    systemHealth: system?.services.length
      ? system.services
      : dashboard.systemHealth,
    activeAgents: system?.activeAgents.length
      ? system.activeAgents
      : dashboard.activeAgents,
  };
}
