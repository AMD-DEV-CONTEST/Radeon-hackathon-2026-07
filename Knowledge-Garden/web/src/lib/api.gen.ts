// AUTO-GENERATED from docs/openapi-snapshot.json — do not edit by hand.
// Regenerate via scripts/audit_contracts.sh.

export interface AssessmentIn {
  idempotency_key: string
  recall: string
  session_id: number
  unit_id: number
}

export interface CardOut {
  content: string
  created_at: string
  id: number
  last_reviewed_at?: any
  mastery_level?: number
  skill_id: number
  source_material?: string
  updated_at: string
}

export interface ExtractRequest {
  run_full?: boolean
  skill_id?: any
  skill_name?: string
  text: string
}

export interface HTTPValidationError {
  detail?: ValidationError[]
}

export interface LearningStart {
  idempotency_key?: any
  skill_id: number
}

export interface MaterialIn {
  filename?: string
  skill_id?: any
  skill_name?: string
  text: string
}

export interface OverrideIn {
  unit_id: number
}

export interface ReviewMessage {
  message: string
}

export interface ReviewStart {
  skill_id: number
}

export interface ReviewStartNew {
  skill_id: number
}

export interface ReviewSubmit {
  idempotency_key: string
  recall: string
  unit_id: number
}

export interface SessionOut {
  card_index?: number
  completed_at?: any
  created_at: string
  id: number
  judged?: Record<string, unknown>
  phase?: string
  retries?: number
  skill_id: number
  status: string
  total_cards?: number
  transcript?: any[]
  user_override?: boolean
}

export interface SkillCreate {
  description?: string
  name: string
}

export interface SkillDetailOut {
  cards?: CardOut[]
  created_at: string
  decay_rate: number
  description?: string
  growth_value: number
  id: number
  last_decay_at?: any
  last_reviewed_at?: any
  name: string
  sessions?: SessionOut[]
  status: string
  updated_at: string
}

export interface SkillListOut {
  skills: SkillOut[]
}

export interface SkillOut {
  card_count?: any
  created_at: string
  decay_rate: number
  description?: string
  growth_value: number
  id: number
  last_decay_at?: any
  last_reviewed_at?: any
  name: string
  status: string
  updated_at: string
}

export interface StatsOut {
  active_sessions: number
  assessment_due?: number
  avg_growth: number
  cards: number
  failed_extractions?: number
  pending_extractions?: number
  preview_units?: number
  review_due?: number
  sessions: number
  skills: number
  total_growth: number
  verified_units?: number
}

export interface ValidationError {
  ctx?: Record<string, unknown>
  input?: any
  loc: any[]
  msg: string
  type: string
}
