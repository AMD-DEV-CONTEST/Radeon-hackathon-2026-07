import type {
  AdminAnalytics,
  AdminDashboard,
  AdminInterviewsResponse,
  AdminSystemResponse,
  AdminUsersResponse,
} from "@/features/admin/types/admin.types";

export async function simulateNetworkLatency(
  ms: number = 380
): Promise<void> {
  await new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

export const MOCK_ADMIN_DASHBOARD: AdminDashboard = {
  overview: {
    totalUsers: 18420,
    activeCandidates: 1264,
    activeInterviews: 42,
    aiAgentsRunning: 14,
    region: "US-EAST-1",
    globalHealthPercent: 99.4,
  },
  kpis: [
    {
      id: "today",
      label: "Today's Interviews",
      value: 248,
      delta: 12.4,
      icon: "interviews",
    },
    {
      id: "active",
      label: "Active Interviews",
      value: 42,
      delta: 4.1,
      icon: "active",
    },
    {
      id: "average",
      label: "Average Score",
      value: 78.4,
      delta: -2.1,
      icon: "score",
    },
    {
      id: "hire",
      label: "Hire Rate",
      value: 18.2,
      suffix: "%",
      delta: 0.8,
      icon: "hire",
    },
  ],
  statistics: {
    daily: 248,
    weekly: 1420,
    monthly: 5860,
    averageScore: 78.4,
    hiringSuccessRate: 18.2,
  },
  interviewTrends: [
    { label: "Jan", volume: 320, quality: 74 },
    { label: "Feb", volume: 410, quality: 76 },
    { label: "Mar", volume: 390, quality: 78 },
    { label: "Apr", volume: 480, quality: 80 },
    { label: "May", volume: 520, quality: 79 },
    { label: "Jun", volume: 610, quality: 82 },
  ],
  userGrowth: [
    { label: "Jan", users: 9200 },
    { label: "Feb", users: 10400 },
    { label: "Mar", users: 11800 },
    { label: "Apr", users: 13600 },
    { label: "May", users: 15800 },
    { label: "Jun", users: 18420 },
  ],
  agentUsage: [
    { label: "Resume", usage: 82 },
    { label: "Planner", usage: 91 },
    { label: "Technical", usage: 88 },
    { label: "Behavior", usage: 74 },
    { label: "Eval", usage: 79 },
  ],
  platformUsage: [
    { label: "Mon", sessions: 420, apiCalls: 18200 },
    { label: "Tue", sessions: 510, apiCalls: 21400 },
    { label: "Wed", sessions: 480, apiCalls: 20100 },
    { label: "Thu", sessions: 560, apiCalls: 23800 },
    { label: "Fri", sessions: 610, apiCalls: 25600 },
    { label: "Sat", sessions: 290, apiCalls: 12100 },
    { label: "Sun", sessions: 240, apiCalls: 9800 },
  ],
  systemPerformance: [
    { label: "0s", cpu: 22, memory: 48, latencyMs: 110 },
    { label: "10s", cpu: 28, memory: 52, latencyMs: 124 },
    { label: "20s", cpu: 34, memory: 55, latencyMs: 118 },
    { label: "30s", cpu: 41, memory: 61, latencyMs: 142 },
    { label: "40s", cpu: 36, memory: 58, latencyMs: 130 },
    { label: "50s", cpu: 29, memory: 54, latencyMs: 121 },
  ],
  skillTrends: [
    { skill: "Go", demand: 88, supply: 54 },
    { skill: "AI/ML Ops", demand: 92, supply: 41 },
    { skill: "React/Next", demand: 76, supply: 68 },
    { skill: "Rust", demand: 84, supply: 32 },
  ],
  liveSessions: [
    {
      id: "AVX-8841",
      candidateName: "Elena Rodriguez",
      candidateInitials: "ER",
      role: "Sr. Backend Lead",
      score: 91,
      elapsed: "24m 12s",
      status: "live",
    },
    {
      id: "AVX-8842",
      candidateName: "Marcus Chen",
      candidateInitials: "MC",
      role: "DevOps Engineer",
      score: 84,
      elapsed: "18m 04s",
      status: "live",
    },
    {
      id: "AVX-8843",
      candidateName: "Priya Nair",
      candidateInitials: "PN",
      role: "Staff Frontend",
      score: 88,
      elapsed: "11m 41s",
      status: "live",
    },
    {
      id: "AVX-8844",
      candidateName: "Jonah Blake",
      candidateInitials: "JB",
      role: "Platform Architect",
      score: 79,
      elapsed: "07m 22s",
      status: "queued",
    },
  ],
  recentCandidates: [
    {
      id: "C-1001",
      name: "Adrian Thorne",
      initials: "AT",
      position: "Principal Engineer",
      score: 96,
      status: "evaluated",
      reportId: "RPT-AVX-9942",
    },
    {
      id: "C-1002",
      name: "Sofia Patel",
      initials: "SP",
      position: "ML Engineer",
      score: 89,
      status: "interviewing",
      reportId: "RPT-AVX-9910",
    },
    {
      id: "C-1003",
      name: "Liam Ortega",
      initials: "LO",
      position: "SRE Lead",
      score: 82,
      status: "pending",
      reportId: "RPT-AVX-9888",
    },
    {
      id: "C-1004",
      name: "Nora Kim",
      initials: "NK",
      position: "Security Engineer",
      score: 74,
      status: "rejected",
      reportId: "RPT-AVX-9871",
    },
  ],
  recentInterviews: [
    {
      id: "I-2201",
      candidateName: "Elena Rodriguez",
      interviewTitle: "System Design Deep Dive",
      startedAt: "2026-08-06T10:12:00.000Z",
      durationMinutes: 58,
      result: "Strong Hire",
    },
    {
      id: "I-2202",
      candidateName: "Marcus Chen",
      interviewTitle: "Reliability Round",
      startedAt: "2026-08-06T09:40:00.000Z",
      durationMinutes: 46,
      result: "Hire",
    },
    {
      id: "I-2203",
      candidateName: "Priya Nair",
      interviewTitle: "Frontend Architecture",
      startedAt: "2026-08-06T08:15:00.000Z",
      durationMinutes: 52,
      result: "Hold",
    },
  ],
  activeAgents: [
    {
      id: "vox-1",
      name: "Vox-1",
      task: "Architectural Deep-Dive",
      busyPercent: 86,
      status: "busy",
    },
    {
      id: "vox-2",
      name: "Vox-2",
      task: "Behavioral Rubric Scoring",
      busyPercent: 64,
      status: "busy",
    },
    {
      id: "vox-3",
      name: "Vox-3",
      task: "Fact Verification Standby",
      busyPercent: 18,
      status: "standby",
    },
  ],
  systemHealth: [
    {
      id: "api",
      name: "API Server",
      status: "operational",
      detail: "p95 under threshold",
    },
    {
      id: "postgres",
      name: "PostgreSQL",
      status: "operational",
      detail: "Primary replica healthy",
    },
    {
      id: "redis",
      name: "Redis",
      status: "operational",
      detail: "Cache hit ratio 97%",
    },
    {
      id: "ws",
      name: "WebSocket",
      status: "warning",
      detail: "Elevated reconnect rate",
    },
    {
      id: "ai",
      name: "AI Engine",
      status: "operational",
      detail: "Model pool warm",
    },
    {
      id: "storage",
      name: "Storage",
      status: "operational",
      detail: "Object store latency nominal",
    },
  ],
  talentFeed: [
    {
      id: "t1",
      name: "Adrian Thorne",
      title: "Principal Engineer",
      initials: "AT",
      score: 96,
    },
    {
      id: "t2",
      name: "Maya Chen",
      title: "Staff Backend",
      initials: "MC",
      score: 94,
    },
    {
      id: "t3",
      name: "Omar Hassan",
      title: "Infra Lead",
      initials: "OH",
      score: 92,
    },
  ],
  aiReports: [
    {
      id: "r1",
      title: "System Design Breakdown",
      category: "Technical",
      timestamp: "2m ago",
    },
    {
      id: "r2",
      title: "Behavioral Sentiment Map",
      category: "Behavioral",
      timestamp: "15m ago",
    },
    {
      id: "r3",
      title: "Hiring Cohort Snapshot",
      category: "Analytics",
      timestamp: "41m ago",
    },
  ],
  strategy: {
    hotTopic:
      "How would you keep write amplification under control while guaranteeing exactly-once processing?",
    probes: [
      "Ask for failure-mode ownership boundaries",
      "Pressure-test observability and alerting topology",
      "Compare dual-write vs event-sourced migration paths",
    ],
    questionQuality: 92,
    aiConfidence: 98.4,
  },
  notifications: [
    {
      id: "n1",
      kind: "system",
      title: "System alert",
      message: "WebSocket reconnect rate elevated in US-EAST-1A.",
      timestamp: "4m ago",
    },
    {
      id: "n2",
      kind: "failed_interview",
      title: "Failed interview",
      message: "Session AVX-8711 ended due to media permission denial.",
      timestamp: "22m ago",
    },
    {
      id: "n3",
      kind: "ai_warning",
      title: "AI warning",
      message: "Neural Parser entered high-load mode for 3 minutes.",
      timestamp: "38m ago",
    },
    {
      id: "n4",
      kind: "registration",
      title: "New registration",
      message: "12 candidates joined the talent pipeline today.",
      timestamp: "1h ago",
    },
  ],
  quickActions: [
    {
      id: "qa-demo",
      label: "Start Demo",
      href: "/interviews/planning",
      description: "Launch a guided mock interview",
    },
    {
      id: "qa-report",
      label: "Generate Report",
      href: "/interviews/report",
      description: "Open latest evaluation report",
    },
    {
      id: "qa-export",
      label: "Export Analytics",
      href: "/admin",
      description: "Download platform analytics CSV",
    },
    {
      id: "qa-logs",
      label: "View Logs",
      href: "/agents",
      description: "Inspect multi-agent execution logs",
    },
    {
      id: "qa-users",
      label: "Manage Users",
      href: "/settings",
      description: "Open account and access settings",
    },
  ],
  engineVersion: "Vox-Engine v2.4.0 (Stable)",
  lastSyncedAt: "2026-08-06T08:00:00.000Z",
};

export const MOCK_ADMIN_ANALYTICS: AdminAnalytics = {
  statistics: MOCK_ADMIN_DASHBOARD.statistics,
  interviewTrends: MOCK_ADMIN_DASHBOARD.interviewTrends,
  userGrowth: MOCK_ADMIN_DASHBOARD.userGrowth,
  agentUsage: MOCK_ADMIN_DASHBOARD.agentUsage,
  platformUsage: MOCK_ADMIN_DASHBOARD.platformUsage,
  systemPerformance: MOCK_ADMIN_DASHBOARD.systemPerformance,
};

export const MOCK_ADMIN_USERS: AdminUsersResponse = {
  users: MOCK_ADMIN_DASHBOARD.recentCandidates,
  totalUsers: MOCK_ADMIN_DASHBOARD.overview.totalUsers,
};

export const MOCK_ADMIN_INTERVIEWS: AdminInterviewsResponse = {
  liveSessions: MOCK_ADMIN_DASHBOARD.liveSessions,
  recentInterviews: MOCK_ADMIN_DASHBOARD.recentInterviews,
};

export const MOCK_ADMIN_SYSTEM: AdminSystemResponse = {
  services: MOCK_ADMIN_DASHBOARD.systemHealth,
  activeAgents: MOCK_ADMIN_DASHBOARD.activeAgents,
  globalHealthPercent: MOCK_ADMIN_DASHBOARD.overview.globalHealthPercent,
};
