import type {
  CandidateDashboard,
  DashboardInterviewListItem,
  DashboardReportListItem,
} from "@/features/dashboard/types/dashboard.types";

export const DEFAULT_DASHBOARD_CANDIDATE_ID = "AVX-2024-ALEX";

export async function simulateNetworkLatency(
  ms: number = 380
): Promise<void> {
  await new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

export const MOCK_CANDIDATE_DASHBOARD: CandidateDashboard = {
  candidate: {
    id: DEFAULT_DASHBOARD_CANDIDATE_ID,
    fullName: "Alexander Johnson",
    email: "alexander.johnson@example.com",
    currentRole: "Senior Solutions Architect",
    preferredRole: "Principal Engineer",
    experienceLevel: "Senior (12+ years)",
    avatarInitials: "AJ",
    greeting: "Ready for your next high-signal interview session.",
    aiAssistantStatus: "online",
    resumeScore: 91,
    readinessScore: 87,
    resumeStatus: "analyzed",
  },
  monthlyProgress: [
    { label: "May", interviews: 5, averageScore: 83 },
    { label: "Jun", interviews: 4, averageScore: 86 },
    { label: "Jul", interviews: 3, averageScore: 84 },
  ],
  scoreDistribution: [
    { label: "90-100", count: 4 },
    { label: "80-89", count: 8 },
    { label: "70-79", count: 6 },
    { label: "Below 70", count: 2 },
  ],
  averageTechnicalScore: 86,
  averageBehavioralScore: 79,
  metrics: [
    {
      id: "completed",
      label: "Interviews Completed",
      value: 24,
      delta: 12.4,
      icon: "interviews",
    },
    {
      id: "average",
      label: "Average Score",
      value: 84,
      suffix: "/100",
      delta: 4.2,
      icon: "score",
    },
    {
      id: "success",
      label: "Success Rate",
      value: 78,
      suffix: "%",
      delta: 3.1,
      icon: "success",
    },
    {
      id: "practice",
      label: "Total Practice Time",
      value: 18.5,
      suffix: "h",
      delta: -2.1,
      icon: "time",
    },
  ],
  performanceTrend: [
    { label: "Jan", interviews: 2, averageScore: 72 },
    { label: "Feb", interviews: 3, averageScore: 76 },
    { label: "Mar", interviews: 4, averageScore: 79 },
    { label: "Apr", interviews: 3, averageScore: 81 },
    { label: "May", interviews: 5, averageScore: 83 },
    { label: "Jun", interviews: 4, averageScore: 86 },
    { label: "Jul", interviews: 3, averageScore: 84 },
  ],
  weeklyProgress: [
    { day: "Mon", minutes: 45, score: 80 },
    { day: "Tue", minutes: 60, score: 82 },
    { day: "Wed", minutes: 30, score: 78 },
    { day: "Thu", minutes: 75, score: 88 },
    { day: "Fri", minutes: 50, score: 85 },
    { day: "Sat", minutes: 20, score: 74 },
    { day: "Sun", minutes: 40, score: 81 },
  ],
  skillImprovement: [
    { skill: "System Design", previous: 72, current: 92 },
    { skill: "Communication", previous: 68, current: 78 },
    { skill: "Leadership", previous: 55, current: 65 },
    { skill: "Go", previous: 70, current: 88 },
    { skill: "AI/ML Ops", previous: 40, current: 58 },
  ],
  upcomingInterviews: [
    {
      id: "UP-1001",
      company: "CloudStream Dynamics",
      position: "Principal Platform Engineer",
      date: "2026-08-08",
      time: "10:30 AM",
      status: "confirmed",
    },
    {
      id: "UP-1002",
      company: "Northwind Labs",
      position: "Staff Backend Engineer",
      date: "2026-08-12",
      time: "2:00 PM",
      status: "scheduled",
    },
    {
      id: "UP-1003",
      company: "Helix Analytics",
      position: "Senior Solutions Architect",
      date: "2026-08-15",
      time: "11:00 AM",
      status: "scheduled",
    },
  ],
  recentInterviews: [
    {
      id: "RI-2201",
      name: "System Design Deep Dive",
      position: "System Design Deep Dive",
      company: "AgentVox Mock",
      score: 92,
      status: "completed",
      recommendation: "Strong Hire",
      completedAt: "2026-08-05T14:00:00.000Z",
      reportId: "RPT-AVX-9942",
    },
    {
      id: "RI-2202",
      name: "Behavioral Leadership Round",
      position: "Behavioral Leadership Round",
      company: "AgentVox Mock",
      score: 78,
      status: "completed",
      recommendation: "Hire",
      completedAt: "2026-07-28T16:20:00.000Z",
      reportId: "RPT-AVX-9811",
    },
    {
      id: "RI-2203",
      name: "Distributed Systems Drill",
      position: "Distributed Systems Drill",
      company: "Practice Arena",
      score: 86,
      status: "completed",
      recommendation: "Strong Hire",
      completedAt: "2026-07-20T11:10:00.000Z",
      reportId: "RPT-AVX-9720",
    },
  ],
  interviewHistory: [
    {
      id: "IH-1",
      title: "API Design & Scaling",
      date: "2026-07-12",
      score: 81,
      durationMinutes: 55,
      status: "completed",
    },
    {
      id: "IH-2",
      title: "Reliability & SLO Review",
      date: "2026-07-02",
      score: 88,
      durationMinutes: 48,
      status: "completed",
    },
    {
      id: "IH-3",
      title: "Mock Hiring Panel",
      date: "2026-06-21",
      score: 74,
      durationMinutes: 62,
      status: "completed",
    },
  ],
  activityTimeline: [
    {
      id: "ACT-1",
      title: "Report generated",
      description: "Strong Hire recommendation for AVX-9942-JS",
      timestamp: "2m ago",
      category: "Reports",
    },
    {
      id: "ACT-2",
      title: "Skill spike detected",
      description: "System Design score improved +8 this week",
      timestamp: "1h ago",
      category: "Insights",
    },
    {
      id: "ACT-3",
      title: "Practice session completed",
      description: "45 minutes on consensus algorithms",
      timestamp: "Yesterday",
      category: "Practice",
    },
    {
      id: "ACT-4",
      title: "Resume refreshed",
      description: "Dossier readiness updated to 87%",
      timestamp: "2d ago",
      category: "Profile",
    },
  ],
  achievements: {
    highestScore: 96,
    streakDays: 12,
    certifications: [
      "System Design Mastery",
      "Behavioral Clarity",
      "Latency Optimization",
    ],
    badges: [
      {
        id: "b1",
        label: "Top 2%",
        description: "Ranked in top cohort for architecture interviews",
      },
      {
        id: "b2",
        label: "Consistency",
        description: "12-day practice streak",
      },
      {
        id: "b3",
        label: "Signal Sharp",
        description: "Three consecutive Strong Hire mock outcomes",
      },
    ],
  },
  notifications: [
    {
      id: "N-1",
      kind: "reminder",
      title: "Upcoming interview",
      message: "CloudStream Dynamics starts in 2 days at 10:30 AM.",
      timestamp: "Just now",
    },
    {
      id: "N-2",
      kind: "suggestion",
      title: "AI suggestion",
      message: "Practice leadership behavioral probes before Friday.",
      timestamp: "18m ago",
    },
    {
      id: "N-3",
      kind: "activity",
      title: "Recent activity",
      message: "Your latest report is ready to download.",
      timestamp: "1h ago",
    },
  ],
  quickActions: [
    {
      id: "qa-resume",
      label: "Upload Resume",
      href: "/resume/upload",
      description: "Refresh dossier signals",
    },
    {
      id: "qa-mock",
      label: "Start Mock Interview",
      href: "/interviews/planning",
      description: "Launch multi-agent practice",
    },
    {
      id: "qa-reports",
      label: "View Reports",
      href: "/interviews/report",
      description: "Open latest evaluation",
    },
    {
      id: "qa-settings",
      label: "Settings",
      href: "/settings",
      description: "Preferences and notifications",
    },
  ],
  lastSyncedAt: "2026-08-06T07:12:00.000Z",
};

export const MOCK_DASHBOARD_INTERVIEWS: ReadonlyArray<DashboardInterviewListItem> =
  [
    {
      id: "UP-1001",
      title: "Principal Platform Engineer",
      company: "CloudStream Dynamics",
      status: "confirmed",
      score: null,
      scheduledAt: "2026-08-08T10:30:00.000Z",
    },
    {
      id: "RI-2201",
      title: "System Design Deep Dive",
      company: "AgentVox Mock",
      status: "completed",
      score: 92,
      scheduledAt: "2026-08-05T14:00:00.000Z",
    },
    {
      id: "RI-2202",
      title: "Behavioral Leadership Round",
      company: "AgentVox Mock",
      status: "completed",
      score: 78,
      scheduledAt: "2026-07-28T16:20:00.000Z",
    },
  ];

export const MOCK_DASHBOARD_REPORTS: ReadonlyArray<DashboardReportListItem> = [
  {
    id: "RPT-AVX-9942",
    interviewId: "AVX-9942-JS",
    title: "System Design Deep Dive",
    score: 92,
    recommendation: "Strong Hire",
    createdAt: "2026-08-05T15:10:00.000Z",
  },
  {
    id: "RPT-AVX-9811",
    interviewId: "AVX-9811-JS",
    title: "Behavioral Leadership Round",
    score: 78,
    recommendation: "Hire",
    createdAt: "2026-07-28T17:05:00.000Z",
  },
];
