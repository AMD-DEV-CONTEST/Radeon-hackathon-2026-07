import type { LucideIcon } from "lucide-react";
import {
  Activity,
  Brain,
  FileSearch,
  FileText,
  Headphones,
  Mic,
  Network,
  Shield,
  Scale,
} from "lucide-react";

export interface LandingNavLink {
  label: string;
  href: string;
}

export interface LandingFeature {
  title: string;
  description: string;
  icon: LucideIcon;
}

export interface LandingWorkflowStep {
  step: string;
  title: string;
  description: string;
}

export interface LandingTrustPillar {
  title: string;
  description: string;
  icon: LucideIcon;
}

export interface LandingFooterColumn {
  title: string;
  links: ReadonlyArray<{ label: string; href: string }>;
}

export const LANDING_NAV_LINKS: ReadonlyArray<LandingNavLink> = [
  { label: "Platform", href: "#features" },
  { label: "Solutions", href: "#workflow" },
  { label: "Pricing", href: "#cta" },
  { label: "Resources", href: "#trust" },
] as const;

export const LANDING_FEATURES: ReadonlyArray<LandingFeature> = [
  {
    title: "Resume Intelligence",
    description:
      "Deep AI analysis of candidate resumes extracting skills, experience patterns, and competency gaps in seconds.",
    icon: FileSearch,
  },
  {
    title: "Adaptive Technical Questions",
    description:
      "Dynamic question generation that adapts difficulty and topic based on real-time candidate responses.",
    icon: Brain,
  },
  {
    title: "Multi-Agent AI",
    description:
      "Seven specialized AI agents collaborate to conduct comprehensive technical and behavioral assessments.",
    icon: Network,
  },
  {
    title: "Voice-First Interview",
    description:
      "Natural voice conversations with sub-second latency powered by advanced speech synthesis and recognition.",
    icon: Mic,
  },
  {
    title: "Live Evaluation",
    description:
      "Real-time performance scoring across technical depth, communication, confidence, and leadership dimensions.",
    icon: Activity,
  },
  {
    title: "AI Hiring Report",
    description:
      "Comprehensive hiring recommendations with competency matrices, interview summaries, and executive insights.",
    icon: FileText,
  },
] as const;

export const LANDING_WORKFLOW: ReadonlyArray<LandingWorkflowStep> = [
  {
    step: "01",
    title: "Upload Resume",
    description: "Upload candidate resume for AI-powered parsing and analysis.",
  },
  {
    step: "02",
    title: "Resume Analysis",
    description: "Deep skill mapping and competency gap identification.",
  },
  {
    step: "03",
    title: "Interview Planning",
    description: "Dynamic question set generation tailored to the candidate.",
  },
  {
    step: "04",
    title: "Agent Interview",
    description: "Real-time AI voice interview with live transcription.",
  },
  {
    step: "05",
    title: "Hiring Report",
    description: "Final evaluation with actionable hiring recommendations.",
  },
] as const;

export const LANDING_PARTNERS: ReadonlyArray<string> = [
  "Notion",
  "Slack",
  "Linear",
  "Vercel",
  "Stripe",
  "GitHub",
] as const;

export const LANDING_TRUST_PILLARS: ReadonlyArray<LandingTrustPillar> = [
  {
    title: "Enterprise Security",
    description: "SOC 2 aligned controls with encrypted candidate data at rest and in transit.",
    icon: Shield,
  },
  {
    title: "GDPR Compliance",
    description: "Privacy-first processing with configurable retention and audit-ready exports.",
    icon: Scale,
  },
  {
    title: "24/7 Live Support",
    description: "Dedicated onboarding and live support for high-volume hiring teams.",
    icon: Headphones,
  },
] as const;

export const LANDING_FOOTER_COLUMNS: ReadonlyArray<LandingFooterColumn> = [
  {
    title: "Platform",
    links: [
      { label: "Product", href: "#features" },
      { label: "Features", href: "#features" },
      { label: "Pricing", href: "#cta" },
    ],
  },
  {
    title: "Resources",
    links: [
      { label: "Documentation", href: "#" },
      { label: "API Reference", href: "#" },
      { label: "Community", href: "#" },
    ],
  },
  {
    title: "Legal",
    links: [
      { label: "Privacy Policy", href: "#" },
      { label: "Terms of Service", href: "#" },
      { label: "Cookie Policy", href: "#" },
    ],
  },
] as const;
