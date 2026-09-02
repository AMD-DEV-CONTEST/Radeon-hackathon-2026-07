export type ServiceHealthStatus = "operational" | "warning" | "offline";

export type InterviewLiveStatus = "live" | "queued" | "completed";

export type CandidatePipelineStatus =
  | "interviewing"
  | "evaluated"
  | "hired"
  | "rejected"
  | "pending";

export type AdminNotificationKind =
  | "system"
  | "failed_interview"
  | "ai_warning"
  | "registration";

export interface AdminKpi {
  id: string;
  label: string;
  value: number;
  suffix?: string;
  delta: number;
  icon: "interviews" | "active" | "score" | "hire" | "users" | "agents";
}

export interface PlatformOverview {
  totalUsers: number;
  activeCandidates: number;
  activeInterviews: number;
  aiAgentsRunning: number;
  region: string;
  globalHealthPercent: number;
}

export interface InterviewTrendPoint {
  label: string;
  volume: number;
  quality: number;
}

export interface UserGrowthPoint {
  label: string;
  users: number;
}

export interface AgentUsagePoint {
  label: string;
  usage: number;
}

export interface PlatformUsagePoint {
  label: string;
  sessions: number;
  apiCalls: number;
}

export interface SystemPerformancePoint {
  label: string;
  cpu: number;
  memory: number;
  latencyMs: number;
}

export interface SkillTrendPoint {
  skill: string;
  demand: number;
  supply: number;
}

export interface LiveInterviewSession {
  id: string;
  candidateName: string;
  candidateInitials: string;
  role: string;
  score: number;
  elapsed: string;
  status: InterviewLiveStatus;
}

export interface RecentCandidateRow {
  id: string;
  name: string;
  initials: string;
  position: string;
  score: number;
  status: CandidatePipelineStatus;
  reportId: string;
}

export interface RecentInterviewRow {
  id: string;
  candidateName: string;
  interviewTitle: string;
  startedAt: string;
  durationMinutes: number;
  result: string;
}

export interface ActiveAgentRow {
  id: string;
  name: string;
  task: string;
  busyPercent: number;
  status: "busy" | "idle" | "standby";
}

export interface SystemServiceHealth {
  id: string;
  name: string;
  status: ServiceHealthStatus;
  detail: string;
}

export interface TalentFeedItem {
  id: string;
  name: string;
  title: string;
  initials: string;
  score: number;
}

export interface AiReportItem {
  id: string;
  title: string;
  category: string;
  timestamp: string;
}

export interface StrategyInsights {
  hotTopic: string;
  probes: ReadonlyArray<string>;
  questionQuality: number;
  aiConfidence: number;
}

export interface AdminNotification {
  id: string;
  kind: AdminNotificationKind;
  title: string;
  message: string;
  timestamp: string;
}

export interface AdminQuickAction {
  id: string;
  label: string;
  href: string;
  description: string;
}

export interface InterviewStatistics {
  daily: number;
  weekly: number;
  monthly: number;
  averageScore: number;
  hiringSuccessRate: number;
}

export interface AdminDashboard {
  overview: PlatformOverview;
  kpis: ReadonlyArray<AdminKpi>;
  statistics: InterviewStatistics;
  interviewTrends: ReadonlyArray<InterviewTrendPoint>;
  userGrowth: ReadonlyArray<UserGrowthPoint>;
  agentUsage: ReadonlyArray<AgentUsagePoint>;
  platformUsage: ReadonlyArray<PlatformUsagePoint>;
  systemPerformance: ReadonlyArray<SystemPerformancePoint>;
  skillTrends: ReadonlyArray<SkillTrendPoint>;
  liveSessions: ReadonlyArray<LiveInterviewSession>;
  recentCandidates: ReadonlyArray<RecentCandidateRow>;
  recentInterviews: ReadonlyArray<RecentInterviewRow>;
  activeAgents: ReadonlyArray<ActiveAgentRow>;
  systemHealth: ReadonlyArray<SystemServiceHealth>;
  talentFeed: ReadonlyArray<TalentFeedItem>;
  aiReports: ReadonlyArray<AiReportItem>;
  strategy: StrategyInsights;
  notifications: ReadonlyArray<AdminNotification>;
  quickActions: ReadonlyArray<AdminQuickAction>;
  engineVersion: string;
  lastSyncedAt: string;
}

export interface AdminAnalytics {
  statistics: InterviewStatistics;
  interviewTrends: ReadonlyArray<InterviewTrendPoint>;
  userGrowth: ReadonlyArray<UserGrowthPoint>;
  agentUsage: ReadonlyArray<AgentUsagePoint>;
  platformUsage: ReadonlyArray<PlatformUsagePoint>;
  systemPerformance: ReadonlyArray<SystemPerformancePoint>;
}

export interface AdminUsersResponse {
  users: ReadonlyArray<RecentCandidateRow>;
  totalUsers: number;
}

export interface AdminInterviewsResponse {
  liveSessions: ReadonlyArray<LiveInterviewSession>;
  recentInterviews: ReadonlyArray<RecentInterviewRow>;
}

export interface AdminSystemResponse {
  services: ReadonlyArray<SystemServiceHealth>;
  activeAgents: ReadonlyArray<ActiveAgentRow>;
  globalHealthPercent: number;
}
