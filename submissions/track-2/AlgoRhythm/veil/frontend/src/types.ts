// ── Domain types matching the FastAPI backend ──────────────────────────────

export type Role = 'auditor' | 'redactor' | 'viewer'

export type Tier = 'M' | 'C' | 'S'  // Mechanical | Correlational | Stylistic

export type RiskBand = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'

export type EditType = 'suppress' | 'generalize' | 'pseudonymize' | 'restructure' | 'reject'

export interface Span {
  start: number
  end: number
  text: string
  page?: number
  source: string
}

// Role-projected finding (reasoning/spans withheld for non-Auditor)
export interface Finding {
  id: string
  persona: string
  tier: Tier
  claim?: string             // withheld for Viewer
  reasoning?: string         // withheld for non-Auditor
  spans?: Span[]             // withheld for non-Auditor
  severity: number           // 0..1
  candidate_set_size?: number  // Tier C only
  caveat?: string              // Tier S only
  resolved: boolean
}

export interface CurvePoint {
  iteration: number
  residual_risk: number
  risk_band: RiskBand
  utility_retained: number
  findings: number
  elapsed_s: number
  token_retention?: number
  semantic_fidelity?: number
  structure_intact?: number
  redaction_count?: number
  verified?: boolean
  override_applied?: boolean
}

// ── API response types ─────────────────────────────────────────────────────

export interface LoginResponse {
  token: string
  role: Role
  expires_at: number
}

export interface UploadResponse {
  document_id: string
  filename: string
  char_count: number
  word_count: number
  pages: number
}

export interface DocumentResponse {
  document_id: string
  original?: string   // withheld for non-Auditor
  redacted?: string
  curve: CurvePoint[]
  findings: Finding[]
}

export interface SelfTestResponse {
  egress_blocked: boolean
  egress_detail: string
  audit_chain_ok: boolean
  audit_entries: number
  audit_detail: string
  allowed_hosts: string[]
}

export interface AuditLogResponse {
  chain_ok: boolean
  detail: string
  entries: AuditEntry[]
}

export interface AuditEntry {
  seq: number
  ts_ms: number
  action: string
  actor: string
  payload: Record<string, unknown>
  entry_hash: string
}

export interface ChatResponse {
  reply: string
}

export interface OverrideResponse {
  document_id: string
  redacted: string
  curve: CurvePoint[]
  findings: Finding[]
}

// ── WebSocket event types ──────────────────────────────────────────────────

export type WsEvent =
  | { event: 'iteration_start'; iteration: number; budget: number }
  | { event: 'persona_start'; persona: string; iteration: number }
  | { event: 'persona_done'; persona: string; findings: number; tool_calls: number; elapsed_s: number }
  | { event: 'persona_error'; persona: string; error: string }
  | { event: 'adjudicated'; accepted: number; merged: number; demoted: number; iteration: number }
  | { event: 'scored'; risk: { residual_risk: number; band: RiskBand; findings: number }; utility: { utility_retained: number }; elapsed_s: number }
  | { event: 'repaired'; edits: number; unrepaired: number }
  | { event: 'verify_start' }
  | { event: 'run_complete'; metrics: RunMetrics; stopped_because?: string }
  | { event: 'final'; findings: Finding[]; redacted: string; curve: CurvePoint[]; stopped_because?: string }
  | { event: 'error'; detail: string }

export interface RunMetrics {
  calls: number
  prompt_tokens: number
  completion_tokens?: number
  mean_tokens_per_second?: number
  mean_ttft_s?: number
  prefix_cache?: {
    available: boolean
    gpu_prefix_cache_hit_rate?: number
    gpu_cache_usage_perc?: number
  }
}

// ── UI state types ─────────────────────────────────────────────────────────

export type PersonaId =
  | 'Layout-Forensicist'
  | 'Data-Broker'
  | 'Insider'
  | 'Journalist'
  | 'Stylometrist'

export type PersonaStatus = 'idle' | 'attacking' | 'hit' | 'ok' | 'error' | 'skipped'

export interface PersonaState {
  id: PersonaId
  label: string
  status: PersonaStatus
  findings: number
  toolCalls: number
  elapsedS?: number
  error?: string
}

export interface IterationState {
  iteration: number
  status: 'running' | 'done'
  findings: number
  risk?: number
  band?: RiskBand
  elapsedS?: number
}

export interface DocumentRecord {
  document_id: string
  filename: string
  char_count: number
  word_count: number
  pages: number
  uploadedAt: number
  status: 'uploaded' | 'audited' | 'verified'
  lastRisk?: number
  lastBand?: RiskBand
  lastUtility?: number
}

// ── Auth context ───────────────────────────────────────────────────────────

export interface AuthState {
  token: string
  role: Role
  expiresAt: number
}

// Capability matrix (mirrors backend CAPABILITIES)
export const CAPABILITIES: Record<Role, Set<string>> = {
  auditor: new Set(['run_attack', 'view_findings', 'view_reasoning', 'view_evidence',
                    'propose_edits', 'apply_edits', 'export_report', 'view_audit',
                    'view_document', 'view_risk_score']),
  redactor: new Set(['view_findings', 'propose_edits', 'apply_edits', 'export_report',
                     'view_document', 'view_risk_score']),
  viewer: new Set(['view_document', 'view_risk_score']),
}

export function can(role: Role, capability: string): boolean {
  return CAPABILITIES[role]?.has(capability) ?? false
}

// ── Persona metadata ───────────────────────────────────────────────────────

export const PERSONAS: { id: PersonaId; label: string; description: string }[] = [
  { id: 'Layout-Forensicist', label: 'Layout Forensicist', description: 'Structural & mechanical extraction' },
  { id: 'Data-Broker',        label: 'Data Broker',        description: 'Quasi-identifier correlation' },
  { id: 'Insider',            label: 'Insider',            description: 'Insider knowledge inference' },
  { id: 'Journalist',         label: 'Journalist',         description: 'Public-source correlation' },
  { id: 'Stylometrist',       label: 'Stylometrist',       description: 'Authorship & style analysis' },
]

export const TIER_LABELS: Record<Tier, string> = {
  M: 'Mechanical',
  C: 'Correlational',
  S: 'Stylistic',
}

export const BAND_ORDER: Record<RiskBand, number> = {
  LOW: 0, MEDIUM: 1, HIGH: 2, CRITICAL: 3,
}
