export interface Finding {
  label: string;
  confidence: number;
  region?: [number, number, number, number];
  heatmap_b64?: string;
}

export interface LocalizationMap {
  finding: string;
  heatmap: string;
  segmentation_mask?: string;
}

export interface ChatTurn {
  role: 'system' | 'user' | 'assistant';
  content: string;
  image_b64?: string;
}

export interface AnalysisResponse {
  image_id: string;
  findings: Finding[];
  confidence_scores: Record<string, number>;
  localization_maps: LocalizationMap[];
  report: string;
  report_source: 'llm' | 'template';
  findings_section: string;
  impression_section: string;
  mask_b64?: string;
  evidence_type: 'attention' | 'gradcam';
  elapsed_seconds: number;
  chat_seed: ChatTurn[];
}

export interface GenerateReportResponse {
  report: string;
  report_source: 'llm' | 'template';
  findings_section: string;
  impression_section: string;
  tokens_generated: number;
  latency_seconds: number;
  chat_seed: ChatTurn[];
}

export interface ChatRequest {
  report: string;
  findings: Finding[];
  question: string;
  max_tokens?: number;
  history?: ChatTurn[];
}

export interface ChatResponse {
  answer: string;
  referenced_finding?: string;
}

export interface ChatStatus {
  state: 'idle' | 'downloading' | 'loading' | 'ready' | 'error';
  progress: number;
  message: string;
  model_path?: string;
  model_name?: string;
}