export type HiringRecommendation =
  | "Strong Hire"
  | "Hire"
  | "Hold"
  | "No Hire";

export type CompletionStatus = "completed" | "partial" | "abandoned";

export type PipelineStageStatus = "completed" | "active" | "upcoming";

export interface PresentationCandidate {
  id: string;
  fullName: string;
  appliedRole: string;
  company: string;
  avatarInitials: string;
  interviewDate: string;
}

export interface PresentationScores {
  overall: number;
  technical: number;
  communication: number;
  behavioral: number;
  confidence: number;
  problemSolving: number;
  collaboration: number;
}

export interface CompetencyPoint {
  subject: string;
  score: number;
  fullMark: number;
}

export interface SkillBreakdownItem {
  label: string;
  score: number;
}

export interface ScoreTrendPoint {
  label: string;
  score: number;
}

export interface EvaluationTimelinePoint {
  minute: number;
  engagement: number;
  technical: number;
}

export interface AiInsights {
  strengths: ReadonlyArray<string>;
  weaknesses: ReadonlyArray<string>;
  keyObservations: ReadonlyArray<string>;
  redFlags: ReadonlyArray<string>;
  positiveSignals: ReadonlyArray<string>;
}

export interface InterviewHighlight {
  id: string;
  label: string;
  title: string;
  detail: string;
}

export interface ImprovementSuggestion {
  id: string;
  area: string;
  suggestion: string;
  priority: "low" | "medium" | "high";
}

export interface PipelineStage {
  id: string;
  label: string;
  status: PipelineStageStatus;
  completedAt?: string;
}

export interface PresentationDashboard {
  id: string;
  reportId: string;
  candidate: PresentationCandidate;
  recommendation: HiringRecommendation;
  recommendationExplanation: string;
  scores: PresentationScores;
  executiveSummary: string;
  durationMinutes: number;
  totalQuestions: number;
  completionStatus: CompletionStatus;
  competencyMatrix: ReadonlyArray<CompetencyPoint>;
  skillBreakdown: ReadonlyArray<SkillBreakdownItem>;
  scoreTrend: ReadonlyArray<ScoreTrendPoint>;
  evaluationTimeline: ReadonlyArray<EvaluationTimelinePoint>;
  insights: AiInsights;
  highlights: ReadonlyArray<InterviewHighlight>;
  improvements: ReadonlyArray<ImprovementSuggestion>;
  pipeline: ReadonlyArray<PipelineStage>;
  lastSyncedAt: string;
}

export interface PresentationReportLookup {
  id: string;
  candidateId: string;
  recommendation: HiringRecommendation;
  overallScore: number;
}

export interface PresentationCandidateLookup {
  id: string;
  fullName: string;
  appliedRole: string;
  company: string;
}
