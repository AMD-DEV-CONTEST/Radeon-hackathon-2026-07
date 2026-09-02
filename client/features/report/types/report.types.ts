export type HiringRecommendation =
  | "Strong Hire"
  | "Hire"
  | "Hold"
  | "No Hire";

export type TimelineEventType =
  | "question"
  | "speaking"
  | "evaluation"
  | "milestone";

export interface ReportCandidate {
  id: string;
  fullName: string;
  title: string;
  avatarInitials: string;
  avatarUrl?: string;
}

export interface ReportScores {
  overall: number;
  technical: number;
  communication: number;
  behavioral: number;
  confidence: number;
  problemSolving: number;
  leadership: number;
  honesty: number;
}

export interface CompetencyRadarPoint {
  subject: string;
  score: number;
  fullMark: number;
}

export interface ScoreBreakdownItem {
  key:
    | "technical"
    | "communication"
    | "leadership"
    | "problemSolving"
    | "honesty"
    | "behavioral"
    | "confidence";
  label: string;
  score: number;
}

export interface PulsePoint {
  minute: number;
  engagement: number;
  technicalDepth: number;
}

export interface StrengthItem {
  category: "Technical" | "Communication" | "Leadership" | "Collaboration";
  title: string;
  description: string;
  score: number;
}

export interface ImprovementItem {
  category:
    | "Technical Gaps"
    | "Soft Skills"
    | "Communication"
    | "Confidence"
    | "Time Management";
  title: string;
  description: string;
  severity: "low" | "medium" | "high";
}

export interface TranscriptHighlight {
  id: string;
  speaker: "ai" | "candidate";
  timestamp: string;
  text: string;
  tag?: string;
}

export interface TimelineEvent {
  id: string;
  type: TimelineEventType;
  atMinute: number;
  title: string;
  description: string;
}

export interface InterviewReport {
  id: string;
  interviewId: string;
  interviewTitle: string;
  conductedAt: string;
  durationMinutes: number;
  candidate: ReportCandidate;
  recommendation: HiringRecommendation;
  performanceConfidence: number;
  insightQuote: string;
  scores: ReportScores;
  competencyMatrix: ReadonlyArray<CompetencyRadarPoint>;
  scoreBreakdown: ReadonlyArray<ScoreBreakdownItem>;
  interviewPulse: ReadonlyArray<PulsePoint>;
  strengths: ReadonlyArray<StrengthItem>;
  improvements: ReadonlyArray<ImprovementItem>;
  summary: {
    executive: string;
    overallPerformance: string;
    aiFeedback: string;
    finalRecommendation: string;
    executiveNote: string;
  };
  transcriptHighlights: ReadonlyArray<TranscriptHighlight>;
  timeline: ReadonlyArray<TimelineEvent>;
}

export interface GenerateReportRequest {
  interviewId: string;
}

export interface GenerateReportResponse {
  reportId: string;
  status: "queued" | "generating" | "ready";
  interviewId: string;
}

export interface InterviewLookup {
  id: string;
  title: string;
  candidateName: string;
  status: "completed" | "in_progress" | "cancelled";
  durationMinutes: number;
  conductedAt: string;
}
