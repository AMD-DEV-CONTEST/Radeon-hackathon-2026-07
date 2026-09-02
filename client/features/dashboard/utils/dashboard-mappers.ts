import { DASHBOARD_QUICK_ACTIONS } from "@/features/dashboard/constants/dashboard-keys";
import type {
  Achievements,
  ActivityItem,
  CandidateDashboard,
  DashboardCandidate,
  DashboardInterviewListItem,
  DashboardMetric,
  DashboardNotification,
  DashboardReportListItem,
  InterviewHistoryItem,
  InterviewStatus,
  MonthlyProgressPoint,
  NotificationKind,
  PerformancePoint,
  QuickAction,
  RecentInterview,
  RecommendationLabel,
  ScoreDistributionPoint,
  SkillImprovementPoint,
  UpcomingInterview,
  WeeklyProgressPoint,
} from "@/features/dashboard/types/dashboard.types";

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

function unwrapItems(payload: unknown): unknown[] {
  if (Array.isArray(payload)) {
    return payload;
  }
  if (isRecord(payload) && Array.isArray(payload.items)) {
    return payload.items;
  }
  return [];
}

function mapInterviewStatus(value: unknown): InterviewStatus {
  const normalized = asString(value).toLowerCase();
  if (normalized === "confirmed") {
    return "confirmed";
  }
  if (normalized === "live" || normalized === "in_progress") {
    return "live";
  }
  if (normalized === "completed" || normalized === "complete") {
    return "completed";
  }
  if (normalized === "cancelled" || normalized === "canceled") {
    return "cancelled";
  }
  return "scheduled";
}

function mapRecommendation(value: unknown): RecommendationLabel {
  const normalized = asString(value).toLowerCase().replace(/_/g, " ");
  if (normalized === "strong hire") {
    return "Strong Hire";
  }
  if (normalized === "hire") {
    return "Hire";
  }
  if (normalized === "hold" || normalized === "maybe") {
    return normalized === "maybe" ? "Maybe" : "Hold";
  }
  if (normalized === "no hire") {
    return "No Hire";
  }
  if (normalized === "practice") {
    return "Practice";
  }
  return "Hold";
}

function mapMetricIcon(
  value: unknown,
  id: string
): DashboardMetric["icon"] {
  const normalized = asString(value).toLowerCase();
  if (
    normalized === "interviews" ||
    normalized === "score" ||
    normalized === "success" ||
    normalized === "time"
  ) {
    return normalized;
  }

  if (id.includes("score") || id.includes("average")) {
    return "score";
  }
  if (id.includes("success") || id.includes("hiring")) {
    return "success";
  }
  if (id.includes("time") || id.includes("practice")) {
    return "time";
  }
  return "interviews";
}

function splitDateTime(iso: string): { date: string; time: string } {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) {
    return { date: iso.slice(0, 10), time: "" };
  }

  return {
    date: parsed.toISOString().slice(0, 10),
    time: new Intl.DateTimeFormat("en-US", {
      hour: "numeric",
      minute: "2-digit",
    }).format(parsed),
  };
}

function mapMetrics(value: unknown): DashboardMetric[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return compactMap(
    value.map((item, index) => {
      if (!isRecord(item)) {
        return null;
      }

      const id = asString(item.id, `metric-${index}`);
      const label = asString(item.label ?? item.name).trim();
      if (!label) {
        return null;
      }

      return {
        id,
        label,
        value: asNumber(item.value ?? item.count),
        suffix: asString(item.suffix) || undefined,
        delta: asNumber(item.delta ?? item.change),
        icon: mapMetricIcon(item.icon, id),
      };
    })
  );
}

function mapPerformancePoints(value: unknown): PerformancePoint[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return compactMap(
    value.map((item) => {
      if (!isRecord(item)) {
        return null;
      }

      const label = asString(item.label ?? item.period ?? item.month).trim();
      if (!label) {
        return null;
      }

      return {
        label,
        interviews: asNumber(item.interviews ?? item.count),
        averageScore: asNumber(item.average_score ?? item.averageScore ?? item.score),
      };
    })
  );
}

function mapWeeklyProgress(value: unknown): WeeklyProgressPoint[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return compactMap(
    value.map((item) => {
      if (!isRecord(item)) {
        return null;
      }

      const day = asString(item.day ?? item.label).trim();
      if (!day) {
        return null;
      }

      return {
        day,
        minutes: asNumber(item.minutes ?? item.duration_minutes),
        score: asNumber(item.score ?? item.average_score),
      };
    })
  );
}

function mapMonthlyProgress(value: unknown): MonthlyProgressPoint[] {
  return mapPerformancePoints(value);
}

function mapSkillImprovement(value: unknown): SkillImprovementPoint[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return compactMap(
    value.map((item) => {
      if (!isRecord(item)) {
        return null;
      }

      const skill = asString(item.skill ?? item.name).trim();
      if (!skill) {
        return null;
      }

      return {
        skill,
        previous: asNumber(item.previous ?? item.before),
        current: asNumber(item.current ?? item.after ?? item.score),
      };
    })
  );
}

function mapScoreDistribution(value: unknown): ScoreDistributionPoint[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return compactMap(
    value.map((item) => {
      if (!isRecord(item)) {
        return null;
      }

      const label = asString(item.label ?? item.bucket ?? item.range).trim();
      if (!label) {
        return null;
      }

      return {
        label,
        count: asNumber(item.count ?? item.value),
      };
    })
  );
}

function mapUpcoming(value: unknown): UpcomingInterview[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return compactMap(
    value.map((item, index) => {
      if (!isRecord(item)) {
        return null;
      }

      const scheduledAt = asString(
        item.scheduled_at ?? item.started_at ?? item.date
      );
      const { date, time } = splitDateTime(scheduledAt);

      return {
        id: asString(item.id, `upcoming-${index}`),
        company: asString(item.company ?? item.organization, "—"),
        position: asString(item.position ?? item.role ?? item.title),
        date: asString(item.date, date),
        time: asString(item.time, time),
        status: mapInterviewStatus(item.status),
      };
    })
  );
}

function mapRecent(value: unknown): RecentInterview[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return compactMap(
    value.map((item, index) => {
      if (!isRecord(item)) {
        return null;
      }

      const position = asString(item.position ?? item.role ?? item.name ?? item.title);
      const completedAt = asString(
        item.completed_at ?? item.ended_at ?? item.created_at ?? item.date
      );

      return {
        id: asString(item.id, `recent-${index}`),
        name: position,
        position,
        company: asString(item.company ?? item.organization, "—"),
        score: asNumber(item.score ?? item.overall_score),
        status: mapInterviewStatus(item.status ?? "completed"),
        recommendation: mapRecommendation(item.recommendation),
        completedAt,
        reportId: asString(
          item.report_id ?? item.reportId ?? item.id,
          asString(item.id)
        ),
      };
    })
  );
}

function mapHistory(value: unknown): InterviewHistoryItem[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return compactMap(
    value.map((item, index) => {
      if (!isRecord(item)) {
        return null;
      }

      return {
        id: asString(item.id, `history-${index}`),
        title: asString(item.title ?? item.role ?? item.position),
        date: asString(item.date ?? item.started_at ?? item.created_at),
        score: asNumber(item.score),
        durationMinutes: asNumber(
          item.duration_minutes ??
            (item.duration_seconds
              ? asNumber(item.duration_seconds) / 60
              : 0)
        ),
        status: mapInterviewStatus(item.status),
      };
    })
  );
}

function mapActivity(value: unknown): ActivityItem[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return compactMap(
    value.map((item, index) => {
      if (!isRecord(item)) {
        return null;
      }

      return {
        id: asString(item.id, `activity-${index}`),
        title: asString(item.title),
        description: asString(item.description ?? item.message),
        timestamp: asString(item.timestamp ?? item.created_at),
        category: asString(item.category, "General"),
      };
    })
  );
}

function mapNotifications(value: unknown): DashboardNotification[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return compactMap(
    value.map((item, index) => {
      if (!isRecord(item)) {
        return null;
      }

      const kindRaw = asString(item.kind, "activity").toLowerCase();
      const kind: NotificationKind =
        kindRaw === "suggestion" || kindRaw === "reminder"
          ? kindRaw
          : "activity";

      return {
        id: asString(item.id, `notification-${index}`),
        kind,
        title: asString(item.title),
        message: asString(item.message ?? item.description),
        timestamp: asString(item.timestamp ?? item.created_at),
      };
    })
  );
}

function mapQuickActions(value: unknown): QuickAction[] {
  if (!Array.isArray(value) || value.length === 0) {
    return [...DASHBOARD_QUICK_ACTIONS];
  }

  const mapped = compactMap(
    value.map((item, index) => {
      if (!isRecord(item)) {
        return null;
      }

      const label = asString(item.label).trim();
      const href = asString(item.href).trim();
      if (!label || !href) {
        return null;
      }

      return {
        id: asString(item.id, `qa-${index}`),
        label,
        href,
        description: asString(item.description),
      };
    })
  );

  return mapped.length > 0 ? mapped : [...DASHBOARD_QUICK_ACTIONS];
}

function mapAchievements(value: unknown): Achievements {
  if (!isRecord(value)) {
    return {
      highestScore: 0,
      streakDays: 0,
      certifications: [],
      badges: [],
    };
  }

  const badges = Array.isArray(value.badges)
    ? compactMap(
        value.badges.map((item, index) => {
          if (!isRecord(item)) {
            return null;
          }
          return {
            id: asString(item.id, `badge-${index}`),
            label: asString(item.label),
            description: asString(item.description),
          };
        })
      )
    : [];

  const certifications = Array.isArray(value.certifications)
    ? value.certifications.map((item) => asString(item)).filter(Boolean)
    : [];

  return {
    highestScore: asNumber(value.highest_score ?? value.highestScore),
    streakDays: asNumber(value.streak_days ?? value.streakDays),
    certifications,
    badges,
  };
}

function buildOverviewMetrics(overview: Record<string, unknown> | null): DashboardMetric[] {
  if (!overview) {
    return [];
  }

  const definitions: Array<{
    id: string;
    label: string;
    keys: string[];
    suffix?: string;
    icon: DashboardMetric["icon"];
  }> = [
    {
      id: "total",
      label: "Total Interviews",
      keys: ["total_interviews", "totalInterviews"],
      icon: "interviews",
    },
    {
      id: "completed",
      label: "Completed Interviews",
      keys: ["completed_interviews", "completedInterviews"],
      icon: "interviews",
    },
    {
      id: "upcoming",
      label: "Upcoming Interviews",
      keys: ["upcoming_interviews", "upcomingInterviews"],
      icon: "time",
    },
    {
      id: "average",
      label: "Average Score",
      keys: ["average_score", "averageScore"],
      suffix: "/100",
      icon: "score",
    },
    {
      id: "resume",
      label: "Resume Score",
      keys: ["resume_score", "resumeScore"],
      suffix: "%",
      icon: "score",
    },
    {
      id: "readiness",
      label: "AI Readiness Score",
      keys: ["ai_readiness_score", "readiness_score", "readinessScore"],
      suffix: "%",
      icon: "score",
    },
    {
      id: "success",
      label: "Hiring Success Rate",
      keys: ["hiring_success_rate", "success_rate", "successRate"],
      suffix: "%",
      icon: "success",
    },
  ];

  return compactMap(
    definitions.map((definition) => {
      const raw = definition.keys
        .map((key) => overview[key])
        .find((value) => value !== undefined && value !== null);

      if (raw === undefined) {
        return null;
      }

      return {
        id: definition.id,
        label: definition.label,
        value: asNumber(raw),
        suffix: definition.suffix,
        delta: asNumber(overview[`${definition.id}_delta`] ?? overview.delta),
        icon: definition.icon,
      };
    })
  );
}

export function mapDashboardCandidate(dto: unknown): DashboardCandidate {
  const record = isRecord(dto) ? dto : {};
  const fullName = asString(
    record.full_name ?? record.name ?? record.fullName
  ).trim();
  const years = asNumber(
    record.years_of_experience ?? record.yearsOfExperience
  );
  const experienceLevel = asString(
    record.experience_level ??
      record.experienceLevel ??
      (years > 0 ? `${years}+ years` : record.level)
  );

  return {
    id: asString(record.id),
    fullName: fullName || asString(record.email, "Candidate"),
    email: asString(record.email),
    currentRole: asString(record.title ?? record.current_role ?? record.currentRole),
    preferredRole: asString(
      record.target_role ?? record.preferred_role ?? record.preferredRole
    ),
    experienceLevel,
    avatarInitials: getInitials(fullName || asString(record.email)),
    greeting: asString(
      record.greeting,
      "Ready for your next high-signal interview session."
    ),
    aiAssistantStatus: (() => {
      const status = asString(
        record.ai_assistant_status ?? record.aiAssistantStatus,
        "online"
      ).toLowerCase();
      if (status === "analyzing" || status === "idle") {
        return status;
      }
      return "online";
    })(),
    resumeScore: asNumber(record.resume_score ?? record.resumeScore),
    readinessScore: asNumber(
      record.readiness_score ??
        record.ai_readiness_score ??
        record.readinessScore
    ),
    resumeStatus: asString(
      record.resume_status ?? record.resumeStatus,
      "unknown"
    ),
  };
}

export function mapDashboardInterviewItem(
  dto: unknown
): DashboardInterviewListItem | null {
  if (!isRecord(dto)) {
    return null;
  }

  return {
    id: asString(dto.id),
    title: asString(dto.role ?? dto.title ?? dto.position),
    company: asString(dto.company, "—"),
    status: mapInterviewStatus(dto.status),
    score:
      dto.score === null || dto.score === undefined
        ? null
        : asNumber(dto.score),
    scheduledAt: asString(
      dto.started_at ?? dto.scheduled_at ?? dto.created_at
    ),
  };
}

export function mapDashboardReportItem(
  dto: unknown
): DashboardReportListItem | null {
  if (!isRecord(dto)) {
    return null;
  }

  return {
    id: asString(dto.id),
    interviewId: asString(dto.interview_id ?? dto.interviewId),
    title: asString(dto.title ?? dto.summary, "Interview Report"),
    score: asNumber(dto.overall_score ?? dto.score),
    recommendation: mapRecommendation(dto.recommendation),
    createdAt: asString(dto.created_at ?? dto.createdAt),
  };
}

export function mapInterviewList(payload: unknown): DashboardInterviewListItem[] {
  return compactMap(unwrapItems(payload).map(mapDashboardInterviewItem));
}

export function mapReportList(payload: unknown): DashboardReportListItem[] {
  return compactMap(unwrapItems(payload).map(mapDashboardReportItem));
}

export function mapCandidateDashboard(dto: unknown): CandidateDashboard {
  const record = isRecord(dto) ? dto : {};
  const overview = isRecord(record.overview)
    ? record.overview
    : isRecord(record.stats)
      ? record.stats
      : null;

  const metricsFromArray = mapMetrics(record.metrics);
  const metrics =
    metricsFromArray.length > 0
      ? metricsFromArray
      : buildOverviewMetrics(overview);

  const candidateSource =
    record.candidate ?? record.profile ?? record.candidate_summary ?? record;

  const mappedCandidate = mapDashboardCandidate(candidateSource);
  const candidate: DashboardCandidate = {
    ...mappedCandidate,
    resumeScore:
      mappedCandidate.resumeScore ||
      asNumber(overview?.resume_score ?? overview?.resumeScore),
    readinessScore:
      mappedCandidate.readinessScore ||
      asNumber(
        overview?.ai_readiness_score ??
          overview?.readiness_score ??
          overview?.readinessScore
      ),
    resumeStatus:
      mappedCandidate.resumeStatus !== "unknown"
        ? mappedCandidate.resumeStatus
        : asString(overview?.resume_status ?? overview?.resumeStatus, "unknown"),
  };

  const performanceTrend = mapPerformancePoints(
    record.performance_trend ??
      record.performanceTrend ??
      record.interview_statistics
  );
  const weeklyProgress = mapWeeklyProgress(
    record.weekly_progress ?? record.weeklyProgress
  );
  const monthlyProgress = mapMonthlyProgress(
    record.monthly_progress ?? record.monthlyProgress
  );
  const skillImprovement = mapSkillImprovement(
    record.skill_improvement ?? record.skillImprovement
  );
  const scoreDistribution = mapScoreDistribution(
    record.score_distribution ?? record.scoreDistribution
  );

  return {
    candidate,
    metrics,
    performanceTrend,
    weeklyProgress,
    monthlyProgress,
    skillImprovement,
    scoreDistribution,
    averageTechnicalScore: asNumber(
      record.average_technical_score ??
        record.averageTechnicalScore ??
        overview?.average_technical_score
    ),
    averageBehavioralScore: asNumber(
      record.average_behavioral_score ??
        record.averageBehavioralScore ??
        overview?.average_behavioral_score
    ),
    upcomingInterviews: mapUpcoming(
      record.upcoming_interviews ?? record.upcomingInterviews
    ),
    recentInterviews: mapRecent(
      record.recent_interviews ?? record.recentInterviews
    ),
    interviewHistory: mapHistory(
      record.interview_history ?? record.interviewHistory
    ),
    activityTimeline: mapActivity(
      record.activity_timeline ?? record.activityTimeline
    ),
    achievements: mapAchievements(record.achievements),
    notifications: mapNotifications(record.notifications),
    quickActions: mapQuickActions(record.quick_actions ?? record.quickActions),
    lastSyncedAt: asString(
      record.last_synced_at ?? record.lastSyncedAt,
      new Date().toISOString()
    ),
  };
}

export function mergeDashboardSources(options: {
  dashboard: CandidateDashboard;
  candidate?: DashboardCandidate | null;
  interviews?: ReadonlyArray<DashboardInterviewListItem>;
  reports?: ReadonlyArray<DashboardReportListItem>;
}): CandidateDashboard {
  const { dashboard, candidate, interviews = [], reports = [] } = options;

  const mergedCandidate = candidate
    ? {
        ...dashboard.candidate,
        ...candidate,
        resumeScore:
          candidate.resumeScore || dashboard.candidate.resumeScore,
        readinessScore:
          candidate.readinessScore || dashboard.candidate.readinessScore,
      }
    : dashboard.candidate;

  let upcoming = dashboard.upcomingInterviews;
  let recent = dashboard.recentInterviews;
  let history = dashboard.interviewHistory;

  if (upcoming.length === 0 && interviews.length > 0) {
    upcoming = interviews
      .filter(
        (item) =>
          item.status === "scheduled" ||
          item.status === "confirmed" ||
          item.status === "live"
      )
      .map((item) => {
        const { date, time } = splitDateTime(item.scheduledAt);
        return {
          id: item.id,
          company: item.company,
          position: item.title,
          date,
          time,
          status: item.status,
        };
      });
  }

  if (recent.length === 0 && interviews.length > 0) {
    const reportByInterview = new Map(
      reports.map((report) => [report.interviewId, report])
    );

    recent = interviews
      .filter((item) => item.status === "completed")
      .map((item) => {
        const report = reportByInterview.get(item.id);
        return {
          id: item.id,
          name: item.title,
          position: item.title,
          company: item.company,
          score: item.score ?? report?.score ?? 0,
          status: item.status,
          recommendation: report?.recommendation ?? "Hold",
          completedAt: item.scheduledAt,
          reportId: report?.id ?? item.id,
        };
      });
  }

  if (history.length === 0 && interviews.length > 0) {
    history = interviews.map((item) => ({
      id: item.id,
      title: item.title,
      date: item.scheduledAt,
      score: item.score ?? 0,
      durationMinutes: 0,
      status: item.status,
    }));
  }

  return {
    ...dashboard,
    candidate: mergedCandidate,
    upcomingInterviews: upcoming,
    recentInterviews: recent,
    interviewHistory: history,
    quickActions:
      dashboard.quickActions.length > 0
        ? dashboard.quickActions
        : [...DASHBOARD_QUICK_ACTIONS],
  };
}
