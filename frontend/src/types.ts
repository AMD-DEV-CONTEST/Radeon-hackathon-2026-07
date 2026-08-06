export interface IntentTrajectory {
  label: string;
  val: string;
}

export interface IntentCompiled {
  fuzzyText: string;
  intentType: string;
  topics: string[];
  artifact: string;
  memoryClues: string;
  relation: string;
  confidence: number;
  trajectory: IntentTrajectory[];
  artifactTypes?: string[];
  entities?: string[];
  timeHints?: string[];
  expandedTerms?: string[];
  searchScope?: string[];
  clarificationNeeded?: boolean;
  clarificationQuestion?: string;
  compiler?: string;
}

export interface EvidenceItem {
  id: string; // e.g. E-01
  filename: string;
  status: 'signed' | 'draft' | 'internal' | 'redacted';
  page: number;
  section: string;
  score: number; // e.g. 0.94
  hashVerified: boolean;
  sha256: string;
  content: string;
  sourcePath?: string;
  evidenceSha256?: string;
  matchReasons?: string[];
  locator?: string;
  parentId?: string;
  contextText?: string;
}

export interface TimelineEvent {
  date: string;
  event: string;
  status: 'VALID' | 'CONDITIONAL' | 'UNENFORCEABLE' | 'PROTECTED';
}

export interface CourtroomVerdict {
  verdictStatus: string;
  verdictTitle: string;
  verdictSubtitle: string;
  confidence: number;
  prosecution: string[];
  defense: string[];
  citedEvidence: string[];
  timeline: TimelineEvent[];
  missingEvidence: string[];
  nextAction: string;
  verdictCode?: string;
}

export interface SecurityRecord {
  file: string;
  sourcePath?: string;
  line: number;
  type: string;
  maskedValue: string;
  fingerprint: string;
  score?: number;
  matchReasons?: string[];
}

export interface RuntimeStats {
  gpuModel: string;
  rocmVersion: string;
  hipStatus: string;
  modelResident: string;
  precision: string;
  vramUsed: number;
  vramTotal: number;
  tokenSpeed: number;
  externalCalls: number;
  available?: boolean;
  error?: string;
  service?: string;
  contextLength?: number;
  dtype?: string;
  quantization?: string;
  gpuArchitecture?: string;
}

export interface CaseData {
  id: string;
  title: string;
  query: string;
  intent: IntentCompiled;
  evidenceList: EvidenceItem[];
  courtroom: CourtroomVerdict;
  route?: string;
  status?: string;
  error?: string;
  workspace?: string;
  indexedSources?: number;
  indexedChunks?: number;
  runtime?: RuntimeStats;
  telemetry?: Record<string, unknown>;
  securityRecords?: SecurityRecord[];
  fileMatches?: Array<{
    source: string;
    sourcePath: string;
    family: string;
    score: number;
    confidence: number;
    reasons: string[];
    duplicatePaths: string[];
    evidenceIds: string[];
  }>;
  retrievalDecision?: {
    status: 'confident' | 'ambiguous' | 'multiple_matches' | 'no_match';
    confidence: number;
    reason: string;
    clarification_question: string;
    top_score: number;
    score_margin: number;
  };
  retrievalQueryId?: string;
  artifactSummary?: Record<string, unknown> | null;
  scan?: Record<string, unknown> | null;
}

export interface RedactedRecord {
  file: string;
  line: number;
  type: string;
  maskedValue: string;
  fingerprint: string;
}
