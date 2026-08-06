/**
 * Centralised helpers for routing hardware-related API calls to the
 * BotverseX Local Agent running on the user's machine.
 *
 * In local dev (Vite proxy on localhost), relative paths work as-is.
 * In production, catalog/read APIs use same-origin (nginx → cloud realtime).
 * After /setup detects a Local Agent, absolute URLs target the user's machine
 * (localhost or LAN) for hardware control.
 */

const LOCAL_AGENT_KEY = 'botversex_local_agent_url'
const DEFAULT_URL = 'https://localhost:8002'

/** Paths that always hit the cloud realtime service (same-origin), even with a saved Local Agent. */
const CATALOG_PATH_PREFIXES = ['/api/robots', '/api/runtimes', '/api/urdf'] as const

export function getLocalAgentUrl(): string {
  if (typeof window === 'undefined') return DEFAULT_URL
  return localStorage.getItem(LOCAL_AGENT_KEY) || DEFAULT_URL
}

export function setLocalAgentUrl(url: string): void {
  localStorage.setItem(LOCAL_AGENT_KEY, url.replace(/\/+$/, ''))
}

export function clearLocalAgentUrl(): void {
  localStorage.removeItem(LOCAL_AGENT_KEY)
}

/** True when the user (or /setup health check) saved a Local Agent base URL. */
export function hasConfiguredLocalAgent(): boolean {
  if (typeof window === 'undefined') return false
  const stored = localStorage.getItem(LOCAL_AGENT_KEY)
  return Boolean(stored?.trim())
}

export function isLocalDev(): boolean {
  if (typeof window === 'undefined') return true
  const h = window.location.hostname
  const port = window.location.port
  // Vite demo on LAN (e.g. http://192.168.x.x:5173) must still use same-origin proxy.
  if (port === '5173' || port === '4173') return true
  return (
    h === 'localhost' ||
    h === '127.0.0.1' ||
    /^192\.168\.\d+\.\d+$/.test(h) ||
    /^10\.\d+\.\d+\.\d+$/.test(h) ||
    /^172\.(1[6-9]|2\d|3[0-1])\.\d+\.\d+$/.test(h)
  )
}

export type AgentProbeResult = {
  ok: boolean
  url: string | null
  via: 'vite-proxy' | 'direct' | null
  lastError?: string
  tried: string[]
}

/** Probe Local Agent health. Local dev prefers Vite proxy (same-origin, no cert issues). */
export async function probeLocalAgentHealth(): Promise<AgentProbeResult> {
  const tried: string[] = []
  let lastError = '无法连接 Local Agent'

  if (isLocalDev()) {
    tried.push('同源代理 /api/setup/health')
    try {
      const res = await fetch('/api/setup/health', { signal: AbortSignal.timeout(4000) })
      if (res.ok) {
        const url = 'http://127.0.0.1:8002'
        setLocalAgentUrl(url)
        return { ok: true, url, via: 'vite-proxy', tried }
      }
      lastError = `开发服务器代理返回 ${res.status}（请确认 apps/realtime 里 Agent 在 :8002 运行，且已执行 npm run dev）`
    } catch (e) {
      lastError =
        e instanceof Error
          ? `${e.message}（请确认 Vite 已启动：cd apps/web && npm run dev）`
          : '开发代理请求失败'
    }
  }

  const saved = getLocalAgentUrl()
  const candidates = isLocalDev()
    ? [
        'http://127.0.0.1:8002',
        'http://localhost:8002',
        saved.replace(/^https:/, 'http:'),
        'https://127.0.0.1:8002',
        'https://localhost:8002',
      ]
    : [
        saved,
        'https://localhost:8002',
        'https://127.0.0.1:8002',
        saved.replace(/^http:/, 'https:'),
        'http://127.0.0.1:8002',
        'http://localhost:8002',
      ]

  const seen = new Set<string>()
  for (const base of candidates) {
    if (!base || seen.has(base)) continue
    seen.add(base)
    const label = `${base}/api/setup/health`
    tried.push(label)
    try {
      const res = await fetch(`${base}/api/setup/health`, {
        signal: AbortSignal.timeout(4000),
      })
      if (res.ok) {
        setLocalAgentUrl(base)
        return { ok: true, url: base, via: 'direct', tried }
      }
      lastError = `${label} 返回 ${res.status}`
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'network error'
      if (base.startsWith('https:')) {
        lastError = `${msg}（HTTPS 需先在浏览器打开 ${base} 并信任自签证书）`
      } else {
        lastError = msg
      }
    }
  }

  return { ok: false, url: null, via: null, lastError, tried }
}

/** One-line / short script users paste into a terminal (browser cannot run this for them). */
export function getCustomerAgentStartScript(): string {
  return `cd botversex-local-agent
source .venv/bin/activate    # Windows: .venv\\Scripts\\activate
python run_api.py`
}

/** Developer-only: monorepo apps/realtime with HTTP (no cert trust on Vite). */
export function getDevAgentStartScript(): string {
  return `# 本地开发：复制到终端并保持窗口打开
cd apps/realtime
source .venv/bin/activate    # Windows: .venv\\Scripts\\activate
python run_api.py --http`
}

/** @deprecated Use getCustomerAgentStartScript or getDevAgentStartScript explicitly. */
export function getAgentStartScript(opts?: { http?: boolean; dev?: boolean }): string {
  const useDev = opts?.dev ?? (opts?.http !== false && isLocalDev())
  return useDev ? getDevAgentStartScript() : getCustomerAgentStartScript()
}

function pathOnly(urlPath: string): string {
  const q = urlPath.indexOf('?')
  return q === -1 ? urlPath : urlPath.slice(0, q)
}

export function isCatalogApiPath(path: string): boolean {
  const p = pathOnly(path.startsWith('/') ? path : `/${path}`)
  return CATALOG_PATH_PREFIXES.some((prefix) => p === prefix || p.startsWith(`${prefix}/`))
}

/**
 * Whether this request should target the saved Local Agent base URL.
 * Catalog APIs always use same-origin so /robots works on phones/tablets even when
 * localStorage still has a desktop localhost agent URL (e.g. Chrome sync).
 *
 * T1-1: 虚拟模式（云端内存状态机）必须走同源云端 realtime，绝不能被 localStorage
 * 里残留的 Local Agent URL 劫持到 https://localhost:8002。调用方通过 init.forceSameOrigin
 * 显式声明此调用是云端虚拟路径，agentFetch 会直接走原生 fetch。
 */
export function shouldRouteToLocalAgent(path: string, forceSameOrigin = false): boolean {
  if (forceSameOrigin) return false
  if (isLocalDev() || !hasConfiguredLocalAgent()) return false
  return !isCatalogApiPath(path)
}

const DEFAULT_TIMEOUT_MS = 10_000
const LONG_ACTION_TIMEOUT_MS = 30_000
const LONG_ACTION_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])

/**
 * Smart fetch wrapper: in local dev uses relative paths (Vite proxy).
 * In production, catalog APIs use same-origin; hardware uses Local Agent when configured.
 * Always enforces a timeout so a dead backend can't hang the UI forever.
 *
 * T1-1: `forceSameOrigin` 强制走原生同源 fetch，绕过 localStorage 里残留的 Local Agent
 * URL。云端虚拟 demo（Reachy `?guide=virtual`）必须设此 flag，否则装过 Local Agent 的
 * 浏览器会把 /api/reachy/virtual/* 等请求发到 https://localhost:8002 并失败。
 */
export function agentFetch(
  path: string,
  init?: RequestInit & { timeoutMs?: number; forceSameOrigin?: boolean },
): Promise<Response> {
  const method = (init?.method ?? 'GET').toUpperCase()
  const defaultMs = LONG_ACTION_METHODS.has(method) ? LONG_ACTION_TIMEOUT_MS : DEFAULT_TIMEOUT_MS
  const timeoutMs = init?.timeoutMs ?? defaultMs
  const forceSameOrigin = init?.forceSameOrigin ?? false
  const { timeoutMs: _drop, forceSameOrigin: _drop2, ...rest } = init ?? {}

  const fetchInit: RequestInit = {
    ...rest,
    signal: rest.signal ?? AbortSignal.timeout(timeoutMs),
  }

  if (isLocalDev() || !shouldRouteToLocalAgent(path, forceSameOrigin)) return fetch(path, fetchInit)
  const base = getLocalAgentUrl()
  const url = path.startsWith('/') ? `${base}${path}` : `${base}/${path}`
  return fetch(url, fetchInit).catch(async (err) => {
    // M50：localStorage 可能残留旧的 https://localhost:8002（早期 setup 存的），
    // 而本机 Agent 是纯 HTTP——https 请求必 ERR_SSL_PROTOCOL_ERROR 且每次请求都撞。
    // 回退到同 host 的 http 孪生，成功则记住，后续直接走 http。
    const httpTwin = base.replace(/^https:\/\/(localhost|127\.0\.0\.1)(:\d+)?/, 'http://$1$2')
    if (httpTwin !== base) {
      const httpUrl = path.startsWith('/') ? `${httpTwin}${path}` : `${httpTwin}/${path}`
      const res = await fetch(httpUrl, { ...fetchInit, signal: AbortSignal.timeout(timeoutMs) }).catch(
        () => null,
      )
      if (res && res.ok) {
        setLocalAgentUrl(httpTwin)
        return res
      }
    }
    throw err
  })
}

/**
 * Build a WebSocket URL pointing at the Local Agent.
 */
export function agentWsUrl(path: string, forceSameOrigin = false): string {
  const p = path.startsWith('/') ? path : `/${path}`
  if (isLocalDev() || !shouldRouteToLocalAgent(p, forceSameOrigin)) {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${proto}//${window.location.host}${p}`
  }
  const base = getLocalAgentUrl().replace(/^http/, 'ws')
  return `${base}${p}`
}

/**
 * Build an absolute HTTP URL pointing at the Local Agent.
 * Useful for non-fetch resources like <img src={agentHttpUrl(...)}/>.
 */
export function agentHttpUrl(path: string, forceSameOrigin = false): string {
  const p = path.startsWith('/') ? path : `/${path}`
  if (isLocalDev() || !shouldRouteToLocalAgent(p, forceSameOrigin)) return p
  return `${getLocalAgentUrl()}${p}`
}
