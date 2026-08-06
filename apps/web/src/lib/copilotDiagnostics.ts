/**
 * Browser-side diagnostic checks for BotverseX Copilot.
 *
 * These run entirely in the browser — no backend round-trip needed —
 * and are sent alongside user questions to give context.
 */

import { isLocalDev } from './localAgent'
import type { DiagnoseResponse } from './copilotApi'

const ERROR_RING_SIZE = 20
const recentErrors: string[] = []

let _installed = false

export function installErrorCollector() {
  if (_installed) return
  _installed = true

  const push = (msg: string) => {
    recentErrors.push(msg)
    if (recentErrors.length > ERROR_RING_SIZE) recentErrors.shift()
  }

  window.addEventListener('error', (e) => {
    push(`[js] ${e.message} @ ${e.filename}:${e.lineno}`)
  })

  window.addEventListener('unhandledrejection', (e) => {
    push(`[promise] ${String(e.reason)}`)
  })

  const origFetch = window.fetch
  window.fetch = async function (...args) {
    try {
      const resp = await origFetch.apply(this, args)
      if (!resp.ok) {
        const url = typeof args[0] === 'string' ? args[0] : (args[0] as Request).url
        // Expected when Reachy daemon is not running — don't pollute Copilot error ring.
        if (resp.status === 502 && url.includes('/api/reachy/')) {
          return resp
        }
        push(`[fetch] ${resp.status} ${url}`)
      }
      return resp
    } catch (err) {
      const url = typeof args[0] === 'string' ? args[0] : (args[0] as Request).url
      push(`[fetch] ${String(err)} ${url}`)
      throw err
    }
  }
}

async function probeLocalAgent(): Promise<{ ok: boolean; error?: string; data?: unknown }> {
  // Local dev: same-origin Vite proxy → apps/realtime on :8002.
  if (isLocalDev()) {
    try {
      const r = await fetch('/api/setup/health', { signal: AbortSignal.timeout(4000) })
      if (r.ok) {
        return { ok: true, data: await r.json() }
      }
      return { ok: false, error: `HTTP ${r.status}` }
    } catch (proxyErr) {
      return { ok: false, error: String(proxyErr) }
    }
  }

  // Cloud site: only the user's machine counts as Local Agent (not ECS sidecar).
  const candidates = [
    'https://localhost:8002/api/setup/health',
    'https://127.0.0.1:8002/api/setup/health',
    'http://127.0.0.1:8002/api/setup/health',
    'http://localhost:8002/api/setup/health',
  ]
  let lastError = '本机 Local Agent 未连接'
  for (const url of candidates) {
    try {
      const r = await fetch(url, { signal: AbortSignal.timeout(3000) })
      if (r.ok) {
        return { ok: true, data: await r.json() }
      }
      lastError = `${url} HTTP ${r.status}`
    } catch (err) {
      lastError = err instanceof Error ? err.message : String(err)
    }
  }
  return { ok: false, error: lastError }
}

export interface ClientDiagnostics {
  page: string
  localAgent: { ok: boolean; error?: string; data?: unknown }
  reachy?: {
    daemonOnline?: boolean
    conversationInstalled?: boolean
    conversationRunning?: boolean
    audioFallback?: boolean
    serialConflict?: boolean
  }
  recentErrors: string[]
  timestamp: number
}

/** M25 — extra Reachy Mini probe so the Copilot can match reachy_* playbooks. */
async function probeReachyMini(): Promise<NonNullable<ClientDiagnostics['reachy']>> {
  const out: NonNullable<ClientDiagnostics['reachy']> = {}
  const reachyFetch = async (url: string, ms = 3000): Promise<unknown | null> => {
    try {
      const r = await fetch(url, { signal: AbortSignal.timeout(ms) })
      if (!r.ok) return null
      return await r.json()
    } catch {
      return null
    }
  }

  const daemonStatus = await reachyFetch('/api/reachy/daemon/status') as
    | { state?: string; backend_status?: Record<string, unknown> }
    | null
  out.daemonOnline = daemonStatus?.state === 'running'

  // Daemon offline → every other reachy endpoint will 502 too. Skip to keep console clean.
  if (!out.daemonOnline) {
    // /api/setup/ports does not depend on the daemon; still safe to probe.
    const ports = await reachyFetch('/api/setup/ports') as
      | { ports?: Array<{ robot_guess?: string }> }
      | null
    if (ports?.ports) {
      const guesses = ports.ports
        .map((p) => p.robot_guess)
        .filter((g) => g && g !== 'unknown')
      out.serialConflict = new Set(guesses).size > 1
    }
    return out
  }

  const convStatus = await reachyFetch('/api/reachy/conversation/status') as
    | { running?: boolean; app_installed?: boolean }
    | null
  out.conversationInstalled = !!convStatus?.app_installed
  out.conversationRunning = !!convStatus?.running

  const localDaemon = await reachyFetch('/api/reachy/local-daemon/status') as
    | { audio_fallback_used?: boolean; audio_warning?: string | null }
    | null
  out.audioFallback = !!localDaemon?.audio_fallback_used || !!localDaemon?.audio_warning

  // Serial conflict: more than one robot_guess non-null in /api/setup/ports.
  const ports = await reachyFetch('/api/setup/ports') as
    | { ports?: Array<{ robot_guess?: string }> }
    | null
  if (ports?.ports) {
    const guesses = ports.ports
      .map((p) => p.robot_guess)
      .filter((g) => g && g !== 'unknown')
    out.serialConflict = new Set(guesses).size > 1
  }

  return out
}

export async function collectClientDiagnostics(): Promise<ClientDiagnostics> {
  const localAgent = await probeLocalAgent()
  const path = window.location.pathname
  const onReachyPage = path.includes('reachy')
  // Skip Reachy daemon probes on B601 / generic robots list — avoids 502 console noise.
  const reachy = localAgent.ok && onReachyPage ? await probeReachyMini() : undefined
  return {
    page: path,
    localAgent,
    reachy,
    recentErrors: [...recentErrors],
    timestamp: Date.now(),
  }
}

/** Fix server-side false negatives when browser can reach platform APIs via nginx. */
export async function reconcileDiagnoseForBrowser(
  result: DiagnoseResponse,
): Promise<DiagnoseResponse> {
  const server = { ...result.server, issues: [...(result.server.issues || [])] }
  let matches = [...(result.matches || [])]

  try {
    const healthRes = await fetch('/api/setup/health', { signal: AbortSignal.timeout(4000) })
    if (healthRes.ok) {
      server.realtime = { ...server.realtime, ok: true, error: undefined }
      server.issues = server.issues.filter((i) => i.code !== 'realtime_unreachable')
      matches = matches.filter((m) => m.code !== 'local_agent_unreachable')
    }
  } catch {
    /* keep server probe result */
  }

  try {
    const robotsRes = await fetch('/api/robots', { signal: AbortSignal.timeout(4000) })
    if (robotsRes.ok) {
      const body = await robotsRes.json()
      const count = Array.isArray(body.robots) ? body.robots.length : 0
      if (count > 0) {
        server.robots = { ok: true, count }
        server.issues = server.issues.filter((i) => i.code !== 'robots_api_error')
        matches = matches.filter((m) => m.code !== 'robots_api_error')
      }
    }
  } catch {
    /* keep server probe result */
  }

  // On cloud demo without user hardware, hide ECS-side USB warnings unless on setup/teleop.
  const onHardwarePage = /\/(setup|teleop|robots\/)/.test(result.page || '')
  if (!isLocalDev() && !onHardwarePage) {
    const cloudOnly = new Set([
      'no_cameras',
      'no_serial',
      'dialout_missing',
      'camera_busy',
      'lerobot_missing',
    ])
    server.issues = server.issues.filter((i) => !cloudOnly.has(i.code))
    matches = matches.filter((m) => !cloudOnly.has(m.code))
  }

  const hasError = server.issues.some((i) => i.severity === 'error')
  const hasWarning = server.issues.some((i) => i.severity === 'warning')
  server.overall = hasError ? 'error' : hasWarning ? 'warning' : 'ok'

  return { ...result, server, matches }
}
