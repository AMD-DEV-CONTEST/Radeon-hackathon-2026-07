/**
 * API client for BotverseX Copilot backend.
 */

import type { CopilotAction } from './copilotAgent'
import { getToken } from './auth'
import type { ClientDiagnostics } from './copilotDiagnostics'

const API_BASE = '/api/v1/copilot'

export interface PlaybookMatch {
  code: string
  title: string
  severity: string
  root_cause: string
  fix_steps: string[]
  verify_steps: string[]
  safe_to_show?: boolean
  audience?: string[]
}

export interface SafeDiagnosticSummary {
  page: string
  overall?: string
  checks: {
    cloud_api?: boolean
    database?: boolean
    realtime?: boolean
    robots?: boolean
    llm_enabled?: boolean
  }
  issue_codes: string[]
  client?: {
    local_agent_ok?: boolean
    recent_error_count?: number
  }
  runtime?: {
    cameras?: string
    serial_devices?: number
    dialout?: boolean
    lerobot?: boolean
  }
}

export interface DiagnoseResponse {
  server: {
    overall: string
    issues: Array<{
      severity: string
      code: string
      title: string
      message: string
    }>
    cloud_api: { ok: boolean }
    realtime: { ok: boolean; url: string; error?: string }
    runtime: Record<string, unknown> | null
    robots: { ok: boolean; count: number }
    llm_enabled: boolean
    [key: string]: unknown
  }
  client: ClientDiagnostics | null
  page: string
  matches: PlaybookMatch[]
  actions?: CopilotAction[]
  safe_summary: SafeDiagnosticSummary
}

export interface ChatResponse {
  answer: string
  diagnostics: DiagnoseResponse['server']
  matches?: PlaybookMatch[]
  actions?: CopilotAction[]
  safe_summary?: SafeDiagnosticSummary
  llm_error?: string
}

export async function copilotDiagnose(
  page: string,
  clientDiagnostics: ClientDiagnostics,
): Promise<DiagnoseResponse> {
  const r = await fetch(`${API_BASE}/diagnose`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ page, client_diagnostics: clientDiagnostics }),
  })
  if (!r.ok) throw new Error(friendlyCopilotError(r.status))
  return r.json()
}

export async function copilotChat(
  message: string,
  page: string,
  clientDiagnostics: ClientDiagnostics,
  history: Array<{ role: string; content: string }>,
): Promise<ChatResponse> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`

  const r = await fetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers,
    body: JSON.stringify({
      message,
      page,
      client_diagnostics: clientDiagnostics,
      history,
    }),
  })
  if (r.status === 401) {
    throw new Error('AI 问答需要登录。请先在 /login 登录，或使用「诊断」标签查看 Playbook 修复步骤。')
  }
  if (!r.ok) throw new Error(friendlyCopilotError(r.status))
  return r.json()
}
