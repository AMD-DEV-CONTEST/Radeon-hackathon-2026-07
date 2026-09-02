import type {
  GenerateReportResponse,
  InterviewLookup,
  InterviewReport,
} from "@/features/report/types/report.types";

export const DEFAULT_REPORT_ID = "RPT-AVX-9942";
export const DEFAULT_REPORT_INTERVIEW_ID = "AVX-9942-JS";

export async function simulateNetworkLatency(
  ms: number = 420
): Promise<void> {
  await new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

export const MOCK_INTERVIEW_LOOKUP: InterviewLookup = {
  id: DEFAULT_REPORT_INTERVIEW_ID,
  title: "Senior Solutions Architect — Technical Deep Dive",
  candidateName: "Alexander Johnson",
  status: "completed",
  durationMinutes: 62,
  conductedAt: "2026-08-05T14:00:00.000Z",
};

export const MOCK_INTERVIEW_REPORT: InterviewReport = {
  id: DEFAULT_REPORT_ID,
  interviewId: DEFAULT_REPORT_INTERVIEW_ID,
  interviewTitle: "Senior Solutions Architect — Technical Deep Dive",
  conductedAt: "2026-08-05T14:00:00.000Z",
  durationMinutes: 62,
  candidate: {
    id: "AVX-2024-ALEX",
    fullName: "Alexander Johnson",
    title: "Senior Solutions Architect",
    avatarInitials: "AJ",
  },
  recommendation: "Strong Hire",
  performanceConfidence: 99.4,
  insightQuote:
    "Candidate is within the top 2% of applicants for the Senior Architect role, specifically excelling in Distributed Consensus and API Design.",
  scores: {
    overall: 84,
    technical: 92,
    communication: 78,
    behavioral: 71,
    confidence: 84,
    problemSolving: 88,
    leadership: 65,
    honesty: 96,
  },
  competencyMatrix: [
    { subject: "Technical", score: 92, fullMark: 100 },
    { subject: "Communication", score: 78, fullMark: 100 },
    { subject: "Leadership", score: 65, fullMark: 100 },
    { subject: "Problem Solving", score: 88, fullMark: 100 },
    { subject: "Confidence", score: 84, fullMark: 100 },
    { subject: "Honesty", score: 96, fullMark: 100 },
  ],
  scoreBreakdown: [
    { key: "technical", label: "Technical Depth", score: 92 },
    { key: "communication", label: "Communication", score: 78 },
    { key: "leadership", label: "Leadership", score: 65 },
    { key: "problemSolving", label: "Problem Solving", score: 88 },
    { key: "honesty", label: "Honesty", score: 96 },
  ],
  interviewPulse: [
    { minute: 0, engagement: 62, technicalDepth: 48 },
    { minute: 10, engagement: 74, technicalDepth: 58 },
    { minute: 20, engagement: 81, technicalDepth: 72 },
    { minute: 30, engagement: 69, technicalDepth: 84 },
    { minute: 40, engagement: 88, technicalDepth: 90 },
    { minute: 50, engagement: 76, technicalDepth: 93 },
    { minute: 60, engagement: 84, technicalDepth: 95 },
  ],
  strengths: [
    {
      category: "Technical",
      title: "Distributed Systems Design",
      description:
        "Articulated consensus trade-offs and failure modes with production-grade clarity.",
      score: 94,
    },
    {
      category: "Communication",
      title: "Structured Explanations",
      description:
        "Broke complex architecture choices into clear layers without sacrificing depth.",
      score: 86,
    },
    {
      category: "Leadership",
      title: "Decision Ownership",
      description:
        "Owned architectural bets and explained how they would be socialized across teams.",
      score: 72,
    },
    {
      category: "Collaboration",
      title: "Cross-Functional Framing",
      description:
        "Connected platform work to product outcomes and reliability goals.",
      score: 80,
    },
  ],
  improvements: [
    {
      category: "Soft Skills",
      title: "Team Management Specifics",
      description:
        "Behavioral answers on mentoring and conflict resolution stayed high-level.",
      severity: "medium",
    },
    {
      category: "Time Management",
      title: "Answer Compression",
      description:
        "A few responses ran long before landing the core decision criteria.",
      severity: "low",
    },
    {
      category: "Communication",
      title: "Stakeholder Simplification",
      description:
        "Could tighten non-technical summaries for executive audiences.",
      severity: "low",
    },
    {
      category: "Confidence",
      title: "Ambiguity Handling Pace",
      description:
        "Paused longer than expected when requirements were intentionally incomplete.",
      severity: "medium",
    },
    {
      category: "Technical Gaps",
      title: "Observability Depth",
      description:
        "SLI/SLO narrative was solid, but alerting topology details were thinner.",
      severity: "low",
    },
  ],
  summary: {
    executive:
      "Alexander demonstrated elite architectural judgment for a Senior Solutions Architect mandate, with especially strong signals in distributed systems and API design.",
    overallPerformance:
      "Performance was consistently high across the 62-minute session. Technical depth accelerated after the first system-design prompt and remained elevated through follow-ups.",
    aiFeedback:
      "Candidate showed clarity in architectural decision-making and balanced practical constraints with theoretical knowledge. Team-management behavioral specifics remain the clearest growth area.",
    finalRecommendation:
      "Strong Hire for infrastructure modernization and platform architecture tracks. Pair with a structured leadership coaching plan in the first 90 days.",
    executiveNote:
      "Highest technical proficiency observed in this cohort. Immediate fit for the infrastructure modernization project.",
  },
  transcriptHighlights: [
    {
      id: "th-1",
      speaker: "ai",
      timestamp: "14:12:08",
      text: "How would you keep write amplification under control while guaranteeing exactly-once processing?",
      tag: "System Design",
    },
    {
      id: "th-2",
      speaker: "candidate",
      timestamp: "14:12:41",
      text: "I would isolate the write path behind an idempotent command log, then project into ClickHouse with checkpointed Flink jobs and backpressure-aware consumers.",
      tag: "High Signal",
    },
    {
      id: "th-3",
      speaker: "ai",
      timestamp: "14:38:16",
      text: "Tell me about a time you aligned engineering and product on a risky migration.",
      tag: "Behavioral",
    },
    {
      id: "th-4",
      speaker: "candidate",
      timestamp: "14:38:52",
      text: "I framed the migration as a reliability investment with staged cutovers, dual-write validation, and a rollback budget negotiated with product leadership.",
      tag: "Leadership",
    },
  ],
  timeline: [
    {
      id: "tl-1",
      type: "milestone",
      atMinute: 0,
      title: "Session Started",
      description: "Warm-up and role calibration completed.",
    },
    {
      id: "tl-2",
      type: "question",
      atMinute: 8,
      title: "System Design Prompt",
      description: "Real-time analytics architecture at 100k events/sec.",
    },
    {
      id: "tl-3",
      type: "speaking",
      atMinute: 18,
      title: "Candidate Deep Dive",
      description: "Extended speaking segment on stream processing topology.",
    },
    {
      id: "tl-4",
      type: "evaluation",
      atMinute: 34,
      title: "Technical Spike",
      description: "Technical depth score peaked during consensus discussion.",
    },
    {
      id: "tl-5",
      type: "question",
      atMinute: 46,
      title: "Behavioral Follow-up",
      description: "Leadership and conflict navigation scenarios.",
    },
    {
      id: "tl-6",
      type: "milestone",
      atMinute: 62,
      title: "Session Ended",
      description: "Final recommendation generated by Evaluation Agent.",
    },
  ],
};

export const MOCK_GENERATE_REPORT_RESPONSE: GenerateReportResponse = {
  reportId: DEFAULT_REPORT_ID,
  status: "ready",
  interviewId: DEFAULT_REPORT_INTERVIEW_ID,
};
