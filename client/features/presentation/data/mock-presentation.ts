import type {
  PresentationCandidateLookup,
  PresentationDashboard,
  PresentationReportLookup,
} from "@/features/presentation/types/presentation.types";

export const DEFAULT_PRESENTATION_CANDIDATE_ID = "AVX-2024-ALEX";
export const DEFAULT_PRESENTATION_ID = "PRES-AVX-9942";
export const DEFAULT_PRESENTATION_REPORT_ID = "RPT-AVX-9942";

export async function simulateNetworkLatency(
  ms: number = 400
): Promise<void> {
  await new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

export const MOCK_PRESENTATION: PresentationDashboard = {
  id: DEFAULT_PRESENTATION_ID,
  reportId: DEFAULT_PRESENTATION_REPORT_ID,
  candidate: {
    id: DEFAULT_PRESENTATION_CANDIDATE_ID,
    fullName: "Alexander Johnson",
    appliedRole: "Senior Solutions Architect",
    company: "CloudStream Dynamics",
    avatarInitials: "AJ",
    interviewDate: "2026-08-05T14:00:00.000Z",
  },
  recommendation: "Strong Hire",
  recommendationExplanation:
    "Elite architectural judgment with production-grade distributed systems depth. Immediate fit for infrastructure modernization with a structured leadership coaching plan in the first 90 days.",
  scores: {
    overall: 84,
    technical: 92,
    communication: 78,
    behavioral: 71,
    confidence: 84,
    problemSolving: 88,
    collaboration: 80,
  },
  executiveSummary:
    "Alexander demonstrated top-quartile performance across a 62-minute multi-agent interview. Technical depth accelerated after the first system-design prompt and remained elevated through follow-ups. Communication was clear and structured, with the primary growth area in team-management behavioral specificity.",
  durationMinutes: 62,
  totalQuestions: 12,
  completionStatus: "completed",
  competencyMatrix: [
    { subject: "Technical", score: 92, fullMark: 100 },
    { subject: "Communication", score: 78, fullMark: 100 },
    { subject: "Behavioral", score: 71, fullMark: 100 },
    { subject: "Confidence", score: 84, fullMark: 100 },
    { subject: "Problem Solving", score: 88, fullMark: 100 },
    { subject: "Collaboration", score: 80, fullMark: 100 },
  ],
  skillBreakdown: [
    { label: "System Design", score: 94 },
    { label: "API Design", score: 90 },
    { label: "Distributed Consensus", score: 93 },
    { label: "Observability", score: 76 },
    { label: "Leadership Narrative", score: 68 },
  ],
  scoreTrend: [
    { label: "Q1", score: 72 },
    { label: "Q2", score: 78 },
    { label: "Q3", score: 84 },
    { label: "Q4", score: 88 },
    { label: "Q5", score: 86 },
    { label: "Q6", score: 91 },
  ],
  evaluationTimeline: [
    { minute: 0, engagement: 60, technical: 45 },
    { minute: 10, engagement: 72, technical: 58 },
    { minute: 20, engagement: 80, technical: 74 },
    { minute: 30, engagement: 70, technical: 86 },
    { minute: 40, engagement: 88, technical: 91 },
    { minute: 50, engagement: 78, technical: 93 },
    { minute: 60, engagement: 84, technical: 95 },
  ],
  insights: {
    strengths: [
      "Distributed systems and consensus trade-off clarity",
      "Structured explanations without losing depth",
      "Strong ownership of architectural decisions",
    ],
    weaknesses: [
      "Team-management behavioral answers stayed high-level",
      "Occasional long-winded responses before the decision criteria",
    ],
    keyObservations: [
      "Technical depth peaked during consensus discussion",
      "Candidate consistently grounded answers in production constraints",
      "Collaboration framing connected platform work to product outcomes",
    ],
    redFlags: [
      "None material — monitoring needed only on people-leadership depth",
    ],
    positiveSignals: [
      "Top 2% cohort signal for Senior Architect mandate",
      "Immediate fit for infrastructure modernization track",
      "High honesty and calibration under ambiguity",
    ],
  },
  highlights: [
    {
      id: "h1",
      label: "Best Answer",
      title: "Exactly-once processing at 100k events/sec",
      detail:
        "Idempotent command log + checkpointed Flink projections with backpressure-aware consumers.",
    },
    {
      id: "h2",
      label: "Most Challenging Question",
      title: "Write amplification under consensus constraints",
      detail:
        "Navigated CAP trade-offs and storage projection costs with clear rollback criteria.",
    },
    {
      id: "h3",
      label: "Fastest Response",
      title: "API versioning strategy",
      detail: "12s to a crisp dual-write and contract-testing plan.",
    },
    {
      id: "h4",
      label: "Longest Response",
      title: "Multi-region migration narrative",
      detail: "4m 18s covering staged cutovers, dual-write validation, and rollback budget.",
    },
    {
      id: "h5",
      label: "Most Confident Answer",
      title: "SLO ownership model",
      detail:
        "Clear ownership boundaries between platform and product teams with alerting topology.",
    },
  ],
  improvements: [
    {
      id: "i1",
      area: "Leadership Narrative",
      suggestion:
        "Prepare two concrete conflict-resolution stories with measurable team outcomes.",
      priority: "high",
    },
    {
      id: "i2",
      area: "Answer Compression",
      suggestion:
        "Lead with decision criteria in the first 20 seconds, then expand with trade-offs.",
      priority: "medium",
    },
    {
      id: "i3",
      area: "Observability Depth",
      suggestion:
        "Add alerting topology and error-budget examples to reliability answers.",
      priority: "medium",
    },
    {
      id: "i4",
      area: "Executive Framing",
      suggestion:
        "Practice non-technical summaries for stakeholder alignment scenarios.",
      priority: "low",
    },
  ],
  pipeline: [
    {
      id: "p1",
      label: "Resume Uploaded",
      status: "completed",
      completedAt: "Jul 28",
    },
    {
      id: "p2",
      label: "Resume Analysis",
      status: "completed",
      completedAt: "Jul 28",
    },
    {
      id: "p3",
      label: "Interview Planning",
      status: "completed",
      completedAt: "Aug 1",
    },
    {
      id: "p4",
      label: "Interview Completed",
      status: "completed",
      completedAt: "Aug 5",
    },
    {
      id: "p5",
      label: "AI Evaluation",
      status: "completed",
      completedAt: "Aug 5",
    },
    {
      id: "p6",
      label: "Report Generated",
      status: "completed",
      completedAt: "Aug 5",
    },
    {
      id: "p7",
      label: "Hiring Recommendation",
      status: "active",
      completedAt: "Aug 6",
    },
  ],
  lastSyncedAt: "2026-08-06T07:30:00.000Z",
};

export const MOCK_PRESENTATION_REPORT: PresentationReportLookup = {
  id: DEFAULT_PRESENTATION_REPORT_ID,
  candidateId: DEFAULT_PRESENTATION_CANDIDATE_ID,
  recommendation: "Strong Hire",
  overallScore: 84,
};

export const MOCK_PRESENTATION_CANDIDATE: PresentationCandidateLookup = {
  id: DEFAULT_PRESENTATION_CANDIDATE_ID,
  fullName: "Alexander Johnson",
  appliedRole: "Senior Solutions Architect",
  company: "CloudStream Dynamics",
};
