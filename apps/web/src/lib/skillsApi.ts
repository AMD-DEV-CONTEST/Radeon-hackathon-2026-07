/**
 * Skills API client — talks to apps/api (:8000) /api/v1/skills/*.
 *
 * Keeps the Skills page (and Workflow Skill Invoke node) free of fetch
 * plumbing. Everything here uses authJson so token / 401 handling is unified.
 */
import { authJson, publicJson } from './auth'

export interface SkillParamSchemaEntry {
  key: string
  label: string
  type: 'string' | 'number' | 'bool' | 'enum'
  default?: unknown
  required?: boolean
  min?: number
  max?: number
  options?: string[]
}

export interface Skill {
  skill_id: string
  verb: string
  description?: string
  robot_type: string
  compatible_types: string[]
  joint_count?: number
  train_backend?: string
  min_episodes?: number
  episode_duration_s?: number
  tags?: string[]
  author?: string
  version?: string
  params_schema?: SkillParamSchemaEntry[]
}

export interface RuntimeWithSkills {
  runtime_id: string
  robot_type: string
  display_name: string
  joint_count: number
  joint_names: string[]
  urdf_url: string | null
  supports_telemetry: boolean
  compatible_skill_ids: string[]
}

export interface SkillInstallation {
  id: string
  skill_id: string
  runtime_id: string
  enabled: boolean
  params: Record<string, unknown>
  installed_at: string | null
  updated_at: string | null
}

export type SkillRunStatus =
  | 'queued'
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'cancelled'

export interface SkillRun {
  run_id: string
  skill_id: string
  runtime_id: string
  verb: string
  status: SkillRunStatus
  params: Record<string, unknown>
  result: unknown
  log_excerpt: string | null
  error_msg: string | null
  started_at: string | null
  ended_at: string | null
}

const BASE = '/api/v1/skills'

export async function listSkills(): Promise<{ skills: Skill[]; count: number }> {
  return publicJson(BASE)
}

export async function getSkill(skillId: string): Promise<Skill> {
  return publicJson(`${BASE}/${encodeURIComponent(skillId)}`)
}

export async function listRuntimesWithSkills(): Promise<{
  runtimes: RuntimeWithSkills[]
  count: number
}> {
  return publicJson(`${BASE}/runtimes`)
}

export async function listInstallations(
  runtimeId?: string,
): Promise<{ installations: SkillInstallation[] }> {
  const q = runtimeId ? `?runtime_id=${encodeURIComponent(runtimeId)}` : ''
  return authJson(`${BASE}/installations${q}`)
}

export async function installSkill(
  skillId: string,
  body: {
    runtime_id: string
    runtime_robot_type?: string
    params?: Record<string, unknown>
    enabled?: boolean
  },
): Promise<SkillInstallation> {
  return authJson(`${BASE}/${encodeURIComponent(skillId)}/install`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export async function patchInstallation(
  instId: string,
  body: { enabled?: boolean; params?: Record<string, unknown> },
): Promise<SkillInstallation> {
  return authJson(`${BASE}/installations/${encodeURIComponent(instId)}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

export async function deleteInstallation(instId: string): Promise<{ ok: boolean }> {
  return authJson(`${BASE}/installations/${encodeURIComponent(instId)}`, {
    method: 'DELETE',
  })
}

export async function runSkill(
  skillId: string,
  body: { runtime_id: string; params?: Record<string, unknown> },
): Promise<SkillRun> {
  return authJson(`${BASE}/${encodeURIComponent(skillId)}/run`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export async function listRuns(opts?: {
  skillId?: string
  limit?: number
}): Promise<{ runs: SkillRun[] }> {
  const params = new URLSearchParams()
  if (opts?.skillId) params.set('skill_id', opts.skillId)
  if (opts?.limit) params.set('limit', String(opts.limit))
  const q = params.toString()
  return authJson(`${BASE}/runs${q ? `?${q}` : ''}`)
}

export async function getRun(runId: string): Promise<SkillRun> {
  return authJson(`${BASE}/runs/${encodeURIComponent(runId)}`)
}
