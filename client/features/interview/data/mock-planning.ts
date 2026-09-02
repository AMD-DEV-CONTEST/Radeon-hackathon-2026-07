import type {
  InterviewConfiguration,
  InterviewPlan,
} from "@/features/interview/types/interview.types";

export const DEFAULT_PLANNING_CANDIDATE_ID = "AVX-2024-ALEX";
export const DEFAULT_INTERVIEW_ID = "INT-PLAN-9942";

export const DEFAULT_INTERVIEW_CONFIGURATION: InterviewConfiguration = {
  role: "Principal Engineer",
  difficulty: "extreme",
  durationMinutes: 60,
  questionCount: 12,
  interviewType: "mixed",
};

export const MOCK_INTERVIEW_PLAN: InterviewPlan = {
  id: DEFAULT_INTERVIEW_ID,
  candidate: {
    id: DEFAULT_PLANNING_CANDIDATE_ID,
    fullName: "Alexander Johnson",
    email: "alexander.johnson@example.com",
    title: "Senior Solutions Architect",
    level: "L7 Architect",
    percentileLabel: "Top 2%",
    avatarInitials: "AJ",
    resumeScore: 91,
    readinessScore: 86,
    selectedRole: "Principal Engineer",
    resumeId: "RES-2024-ALEX",
    resumeFileName: "alex-johnson-resume.pdf",
    resumeStatus: "analyzed",
    resumeUploadedAt: "2026-08-01T10:15:00.000Z",
  },
  configuration: DEFAULT_INTERVIEW_CONFIGURATION,
  agents: [
    {
      id: "resume",
      name: "Resume Agent",
      description: "Parses resume signals and maps competency clusters.",
      status: "ready",
      progress: 100,
      ready: true,
    },
    {
      id: "planner",
      name: "Planner Agent",
      description: "Synthesizes roadmap, weights, and multi-agent personas.",
      status: "running",
      progress: 68,
      ready: false,
    },
    {
      id: "technical",
      name: "Technical Agent",
      description: "Generates adaptive system design and coding probes.",
      status: "idle",
      progress: 24,
      ready: false,
    },
    {
      id: "behavioral",
      name: "Behavioral Agent",
      description: "Prepares leadership and conflict scenarios.",
      status: "idle",
      progress: 18,
      ready: false,
    },
    {
      id: "fact-checker",
      name: "Fact Checker",
      description: "Cross-validates claims against resume evidence.",
      status: "idle",
      progress: 12,
      ready: false,
    },
    {
      id: "evaluation",
      name: "Evaluation Agent",
      description: "Configures live scoring dimensions and thresholds.",
      status: "idle",
      progress: 10,
      ready: false,
    },
    {
      id: "hiring",
      name: "Hiring Agent",
      description: "Prepares final recommendation rubric outputs.",
      status: "idle",
      progress: 8,
      ready: false,
    },
  ],
  workflow: [
    {
      id: "step-1",
      step: "01",
      title: "Resume Analysis",
      status: "completed",
      icon: "resume",
    },
    {
      id: "step-2",
      step: "02",
      title: "Interview Planning",
      status: "active",
      icon: "planning",
    },
    {
      id: "step-3",
      step: "03",
      title: "Question Generation",
      status: "pending",
      icon: "questions",
    },
    {
      id: "step-4",
      step: "04",
      title: "Difficulty Selection",
      status: "pending",
      icon: "difficulty",
    },
    {
      id: "step-5",
      step: "05",
      title: "Knowledge Graph",
      status: "pending",
      icon: "graph",
    },
    {
      id: "step-6",
      step: "06",
      title: "Interview Ready",
      status: "pending",
      icon: "ready",
    },
  ],
  checklist: [
    { id: "resume", label: "Resume Uploaded", completed: true },
    { id: "mic", label: "Microphone Ready", completed: true },
    { id: "camera", label: "Camera Ready", completed: false },
    { id: "network", label: "Internet Connected", completed: true },
    { id: "browser", label: "Browser Supported", completed: true },
  ],
  summary: {
    estimatedDurationMinutes: 60,
    expectedQuestionCount: 12,
    skillCoverage: 84,
    confidenceScore: 92,
    planningProgress: 34,
    engineStatus: "SYNTHESIZING ROADMAP",
    difficulty: "extreme",
    skillsToCover: [
      "System Design",
      "Concurrency",
      "Cloud Native",
      "Behavioral",
    ],
  },
  skillDistribution: [
    { label: "Architecture", value: 94 },
    { label: "Backend", value: 88 },
    { label: "DevOps", value: 76 },
    { label: "Leadership", value: 82 },
    { label: "Security", value: 61 },
  ],
  interviewCoverage: [
    { label: "System Design", coverage: 90 },
    { label: "Concurrency", coverage: 78 },
    { label: "Cloud Native", coverage: 85 },
    { label: "Behavioral", coverage: 70 },
    { label: "Security", coverage: 58 },
  ],
  insights: {
    suggestions: [
      "Focus on his tenure at 'CloudStream' and ownership of multi-region reliability.",
      "Probe into his understanding of 'CAP Theorem' under real production constraints.",
    ],
    strengths: [
      { label: "Distributed Sys", value: 92 },
      { label: "Cloud Native", value: 88 },
      { label: "Team Lead", value: 84 },
    ],
    gaps: [
      { label: "Mobile Dev", value: 38 },
      { label: "PyTorch", value: 32 },
      { label: "Data Eng", value: 45 },
    ],
    strategy:
      "AI will begin with high-level architecture then rapidly drill into specific implementation trade-offs if response time is <2s.",
    recommendation:
      "Keep adaptive pathing enabled and allocate extra depth to DevSecOps and data-platform fluency.",
  },
};

export async function simulatePlanningLatency(ms = 420): Promise<void> {
  await new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}
