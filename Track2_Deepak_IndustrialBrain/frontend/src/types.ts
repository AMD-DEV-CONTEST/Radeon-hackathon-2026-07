export interface Session {
  token: string;
  username: string;
  displayName: string;
  role: string;
}

export interface DocumentRecord {
  id: string;
  filename: string;
  uploadDate: string;
  status: 'processing' | 'ready' | 'failed';
  size: number;
}

export interface DashboardData {
  documents: number;
  readyDocuments: number;
  assets: number;
  queries: number;
  assetTags: string[];
  aiOnline: boolean;
  recentQueries: string[];
}

export interface Citation {
  docId: string;
  filename: string;
  page?: number;
  textSnippet: string;
}

export type AnswerFormat = 'paragraph' | 'bullet' | 'table';

export interface ChatAnswer {
  answer: string;
  mode: string;
  format: string;
  confidence: number;
  citations: Citation[];
  assetTag?: string;
  queryId: string;
}

export interface ConversationTurn {
  role: 'user' | 'ai';
  content: string;
  citations?: Citation[];
  id?: string;
}

export interface AssetData {
  tag: string;
  sources: string[];
  failures: string[];
  maintenanceActions: string[];
  dates: string[];
  measurements: Record<string, number>;
  timeline: { date: string; event: string }[];
  evidenceChunks: number;
}

export interface RcaData {
  tag: string;
  rootCause: string;
  contributingFactors: string[];
  recommendations: string[];
  confidenceScore: number;
}

export interface AnalyticsData {
  totalChunks: number;
  totalAssets: number;
  topFailureModes: { label: string; value: number }[];
  topActions: { label: string; value: number }[];
  assetsRankedByRisk: { tag: string; riskScore: number; lastFailure: string }[];
}
