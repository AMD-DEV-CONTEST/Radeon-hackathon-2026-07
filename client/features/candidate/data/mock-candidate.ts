import type {
  CandidateDossier,
  ResumeDetails,
} from "@/features/candidate/types/candidate.types";

export const DEFAULT_CANDIDATE_ID = "AVX-2024-ALEX";

export const MOCK_CANDIDATE_DOSSIER: CandidateDossier = {
  analysisStatus: "complete",
  profile: {
    id: DEFAULT_CANDIDATE_ID,
    resumeId: "RES-2024-ALEX",
    fullName: "Alex Johnson",
    title: "Senior Solutions Architect",
    email: "alex.johnson@cloudstream.io",
    phone: null,
    location: "San Francisco, CA",
    avatarInitials: "AJ",
    yearsOfExperience: 12,
    targetRole: "Principal Engineer",
    summary:
      "Principal-track architect with deep expertise in distributed systems, cloud-native platforms, and high-scale backend design. Strong track record leading platform modernization and mentoring senior engineers.",
  },
  experienceSummary:
    "Senior architecture ownership across cloud-native platforms.",
  educationSummary: "M.S. Computer Science, Stanford University.",
  suggestedInterviewFocus: [
    "Consistency vs availability trade-offs",
    "Security controls in CI/CD",
    "Leadership under architecture conflict",
  ],
  coreCompetencies: [
    "Distributed Systems",
    "Go",
    "Python",
    "AWS",
    "Kubernetes",
    "gRPC",
    "Terraform",
  ],
  skills: [
    { name: "System Design", proficiency: 94, category: "Architecture" },
    { name: "Go", proficiency: 90, category: "Backend" },
    { name: "Kubernetes", proficiency: 86, category: "DevOps" },
    { name: "AWS", proficiency: 88, category: "Cloud" },
    { name: "Python", proficiency: 82, category: "Backend" },
    { name: "React", proficiency: 68, category: "Frontend" },
    { name: "Data Pipelines", proficiency: 54, category: "Data" },
    { name: "Security Hardening", proficiency: 61, category: "Security" },
  ],
  experience: [
    {
      id: "exp-1",
      role: "Senior Architect",
      company: "CloudStream Dynamics",
      startDate: "2021",
      endDate: "Present",
      description:
        "Owns platform architecture for multi-region streaming services and leads design reviews across backend guilds.",
      highlights: [
        "Reduced p99 latency by 37% through event-driven redesign",
        "Standardized service mesh patterns across 40+ microservices",
      ],
    },
    {
      id: "exp-2",
      role: "Backend Lead",
      company: "FinTech Innovate",
      startDate: "2018",
      endDate: "2021",
      description:
        "Led payments platform modernization and introduced reliability engineering practices.",
      highlights: [
        "Delivered idempotent settlement pipelines at 12k TPS",
        "Built on-call framework and SLO culture for critical APIs",
      ],
    },
  ],
  projects: [
    {
      id: "proj-1",
      name: "Global Event Bus",
      role: "Lead Architect",
      description:
        "Designed a fault-tolerant event backbone for cross-region product analytics and workflow orchestration.",
      technologies: ["Go", "Kafka", "Kubernetes", "AWS"],
    },
    {
      id: "proj-2",
      name: "Realtime Risk Engine",
      role: "Technical Lead",
      description:
        "Built a low-latency scoring service with adaptive caching and circuit-breaking for payment risk checks.",
      technologies: ["Python", "Redis", "gRPC", "Terraform"],
    },
  ],
  education: [
    {
      id: "edu-1",
      degree: "M.S. Computer Science",
      institution: "Stanford University",
      year: "2016",
      details: "Focus on distributed systems and cloud computing.",
    },
    {
      id: "edu-2",
      degree: "B.S. Computer Engineering",
      institution: "University of Illinois",
      year: "2014",
      details: "Graduated with honors; systems and networking track.",
    },
  ],
  certifications: [
    {
      id: "cert-1",
      name: "AWS Solutions Architect Professional",
      issuer: "Amazon Web Services",
      year: "2023",
    },
    {
      id: "cert-2",
      name: "Certified Kubernetes Administrator",
      issuer: "CNCF",
      year: "2022",
    },
  ],
  competencies: [
    { subject: "Architecture", candidate: 94, required: 90 },
    { subject: "Backend", candidate: 91, required: 88 },
    { subject: "DevOps", candidate: 78, required: 84 },
    { subject: "Frontend", candidate: 62, required: 70 },
    { subject: "Security", candidate: 68, required: 82 },
    { subject: "Data Science", candidate: 55, required: 75 },
  ],
  strengths: [
    {
      label: "Architecture Design",
      score: 94,
      description:
        "Consistently demonstrates strong multi-service decomposition and trade-off reasoning.",
    },
    {
      label: "System Scalability",
      score: 88,
      description:
        "Excellent depth in throughput planning, caching strategy, and failure isolation.",
    },
  ],
  weaknesses: [
    {
      label: "DevSecOps Workflow",
      score: 62,
      description:
        "Limited evidence of security automation and policy-as-code ownership.",
    },
    {
      label: "Data Engineering",
      score: 45,
      description:
        "Fewer production examples around warehouse modeling and batch/stream hybrid pipelines.",
    },
  ],
  aiSummary:
    "Alex is a strong Principal Engineer candidate for distributed systems roles. Prioritize deep system design probing around consistency models and operational excellence, then validate DevSecOps maturity and data-platform fluency.",
  roadmap: {
    durationMinutes: 60,
    targetRole: "Principal Eng.",
    complexity: "Extreme",
    readinessScore: 86,
    recommendedFocus: [
      "Consistency vs availability trade-offs",
      "Security controls in CI/CD",
      "Leadership under architecture conflict",
    ],
    sections: [
      {
        id: "tech-core",
        title: "Technical Core",
        questions: [
          {
            id: "q-1",
            category: "System Design",
            difficulty: "High",
            prompt:
              "How would you design a globally distributed notification system that avoids the thundering herd problem during recovery?",
          },
          {
            id: "q-2",
            category: "Concurrency",
            difficulty: "Med",
            prompt:
              "Compare optimistic and pessimistic locking for a high-contention inventory reservation service.",
          },
        ],
      },
      {
        id: "leadership",
        title: "Leadership & Soft Skills",
        questions: [
          {
            id: "q-3",
            category: "Conflict",
            difficulty: "High",
            prompt:
              "Tell me about a time you had to pivot architecture mid-project against stakeholder pressure. What did you protect and what did you concede?",
          },
        ],
      },
    ],
  },
};

export const MOCK_RESUME_DETAILS: ResumeDetails = {
  id: "RES-2024-ALEX",
  candidateId: DEFAULT_CANDIDATE_ID,
  fileName: "alex-johnson-resume.pdf",
  uploadedAt: "2026-08-01T10:15:00.000Z",
  fileSize: 245_760,
  status: "analyzed",
  mimeType: "application/pdf",
  parsedSummary:
    "Parsed resume indicates senior architecture ownership, cloud-native delivery, and leadership across platform guilds.",
};

export async function simulateNetworkLatency(ms = 450): Promise<void> {
  await new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}
