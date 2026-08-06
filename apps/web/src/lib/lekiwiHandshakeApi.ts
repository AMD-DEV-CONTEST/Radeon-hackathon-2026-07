/**
 * LeKiwi handshake — P2 closed-loop API client.
 *
 * Wraps /api/lekiwi/handshake/* endpoints on the Local Agent. The progress
 * card uses `getHandshakePlan` on a timer; when a new L-tier is reached it
 * calls `triggerAutoContinue` to kick off norm_stats → train → sync_model.
 */
import { agentFetch } from './localAgent'

export interface LeKiwiHandshakePlanResponse {
  ok: boolean
  repo_id: string
  current_episodes: number
  l1_target: number
  l2_target: number
  l3_target: number
  tier_reached: 'L1' | 'L2' | 'L3' | null
  dataset_path: string
  dataset_exists: boolean
}

export interface LeKiwiHandshakeStatus {
  ok: boolean
  phase?: string
  running?: boolean
  tier?: string
  current_episodes?: number
  repo_id?: string
  norm_stats_ok?: boolean
  norm_stats_log?: string
  train_ok?: boolean
  train_job_id?: string | null
  train_log?: string
  sync_ok?: boolean
  sync_log?: string
  error?: string
  finished?: boolean
  ts?: number
}

export interface AutoContinueRequest {
  repo_id: string
  l1_target?: number
  l2_target?: number
  l3_target?: number
  api_base_url?: string
  api_token?: string
  algorithm?: string
  dataset_id?: string
  model_id?: string
  node_id?: string
  remote_dir?: string
  task_prompt?: string
}

export interface AutoContinueResponse {
  ok: boolean
  triggered: boolean
  tier_reached?: string
  current_episodes?: number
  message?: string
  error?: string
}

export async function getHandshakePlan(opts: {
  repoId: string
  l1Target?: number
  l2Target?: number
  l3Target?: number
}): Promise<LeKiwiHandshakePlanResponse> {
  const res = await agentFetch('/api/lekiwi/handshake/plan', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      repo_id: opts.repoId,
      l1_target: opts.l1Target ?? 20,
      l2_target: opts.l2Target ?? 50,
      l3_target: opts.l3Target ?? 100,
    }),
    timeoutMs: 15_000,
  })
  if (!res.ok) throw new Error(`handshake plan failed: ${res.status}`)
  return (await res.json()) as LeKiwiHandshakePlanResponse
}

export async function triggerAutoContinue(opts: AutoContinueRequest): Promise<AutoContinueResponse> {
  const res = await agentFetch('/api/lekiwi/handshake/auto_continue', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(opts),
    timeoutMs: 30_000,
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(text || `auto_continue failed: ${res.status}`)
  }
  return (await res.json()) as AutoContinueResponse
}

export async function getAutoContinueStatus(): Promise<LeKiwiHandshakeStatus> {
  const res = await agentFetch('/api/lekiwi/handshake/auto_continue/status', {
    timeoutMs: 8_000,
  })
  if (!res.ok) throw new Error(`status failed: ${res.status}`)
  return (await res.json()) as LeKiwiHandshakeStatus
}

/** Human-readable phase label for the chain. */
export function handshakePhaseLabel(phase: string | undefined): string {
  switch (phase) {
    case 'norm_stats':
      return '正在算归一化统计 (norm_stats)'
    case 'train':
      return '正在提交续训任务'
    case 'sync':
      return '正在同步模型到算力节点并热加载'
    case 'done':
      return '闭环完成'
    case 'error':
      return '闭环出错'
    case 'idle':
    default:
      return '空闲'
  }
}
