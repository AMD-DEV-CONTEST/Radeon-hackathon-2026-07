export interface SystemStatus {
  app: string
  version: string
  environment: string
  deployment_mode: string
  auth_enabled: boolean
  model_configured: boolean
  model_reachable: boolean | null
  model_endpoint: string
  model_name: string
  inference_ownership: string
  submission_topology_compliant: boolean
  milvus_ready: boolean
}

export interface AccessSession {
  access_token: string
  token_type: 'Bearer'
  expires_in: number
  expires_at: string
  session_id: string
}

export interface ImageSummary {
  id: string
  thread_id: string
  original_name: string
  mime_type: string
  width: number
  height: number
  sha256: string
  created_at: string
}

export interface EvidenceCard {
  card_id: string
  text: string
  pack: string
  source_title: string
  source_url: string
  license: string
  tags: string[]
  score: number
}

export interface ToolTrace {
  node: string
  tool: string
  status: 'completed' | 'failed' | 'skipped' | 'blocked'
  duration_ms: number
  summary: string
}

export interface MemoryProposal {
  consent_id: string
  thread_id: string
  user_id: string
  text: string
  memory_type: string
  status: 'pending' | 'approved' | 'rejected'
  created_at: string
}

export interface CandidateAssessment {
  image_id: string
  crop_resilience: number
  small_size_clarity: number
  privacy_safety: number
  intent_alignment: number
  contextual_ambiguity: number
  rationale: string
}

export interface CandidateComparison {
  recommended_image_id: string
  candidates: CandidateAssessment[]
  decision_rule: string
  caveat: string
}

export interface AnalysisRunResponse {
  run_id: string
  thread_id: string
  status: 'completed' | 'blocked' | 'failed'
  plan: string[]
  observations: Array<Record<string, unknown>>
  privacy_findings: Array<Record<string, unknown>>
  evidence: EvidenceCard[]
  recalled_memories: Array<Record<string, unknown>>
  comparison: CandidateComparison | null
  memory_proposal: MemoryProposal | null
  report_markdown: string
  tool_trace: ToolTrace[]
  performance_metrics: {
    total_duration_ms: number
    local_tool_duration_ms: number
    model_duration_ms: number
    retrieval_duration_ms: number
    image_count: number
    evidence_count: number
  }
}

export interface MemoryRecord {
  id: string
  user_id: string
  text: string
  memory_type: string
  source_thread_id: string
  consent_id: string
  active: boolean
  created_at: string
}

export interface StreamEvent {
  event: string
  data: Record<string, unknown>
}
