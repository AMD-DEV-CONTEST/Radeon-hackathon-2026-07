import type { HealthResponse, Job, JobCreate, JobListResponse } from './types'

// Default: same-origin /api/v1 (works with the Vite dev proxy and with the
// FastAPI static hosting). Override with VITE_API_BASE for full separation
// (e.g. https://api.example.com/api/v1).
export const API_BASE: string =
  (import.meta.env.VITE_API_BASE as string | undefined) ?? '/api/v1'

const TOKEN_KEY = 'live_science_access_token'

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

let unauthorizedHandler: (() => void) | null = null

/** Called when the backend rejects the stored token (HTTP 401). */
export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler
}

function withAuth(init?: RequestInit): RequestInit {
  const token = getToken()
  if (!token) return init ?? {}
  const headers = new Headers(init?.headers)
  headers.set('Authorization', `Bearer ${token}`)
  return { ...init, headers }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, withAuth(init))
  if (res.status === 401) {
    clearToken()
    unauthorizedHandler?.()
    throw new Error('Session expired, please log in again')
  }
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const body = (await res.json()) as { detail?: unknown }
      if (typeof body.detail === 'string') detail = body.detail
      else if (body.detail != null) detail = JSON.stringify(body.detail)
    } catch {
      // keep the default detail
    }
    throw new Error(detail)
  }
  return (await res.json()) as T
}

const jsonHeaders = { 'Content-Type': 'application/json' }

export const api = {
  login: (token: string) =>
    request<{ ok: boolean; token: string }>('/auth/login', {
      method: 'POST',
      headers: jsonHeaders,
      body: JSON.stringify({ token }),
    }),
  health: () => request<HealthResponse>('/health'),
  createJob: (payload: JobCreate) =>
    request<Job>('/jobs', {
      method: 'POST',
      headers: jsonHeaders,
      body: JSON.stringify(payload),
    }),
  listJobs: (limit = 50, offset = 0) =>
    request<JobListResponse>(`/jobs?limit=${limit}&offset=${offset}`),
  getJob: (id: string) => request<Job>(`/jobs/${encodeURIComponent(id)}`),
}

/** Backend artifact URLs are API-relative; point them at the API origin.
 *  Media tags (<video>/<img>/<a>) cannot send custom headers, so the access
 *  token is appended as an `access_token` query param, which the backend
 *  accepts as an alternative to the Authorization header. */
export function resolveArtifactUrl(pathOrUrl: string): string {
  if (/^https?:\/\//.test(pathOrUrl)) return pathOrUrl
  const origin = API_BASE.startsWith('http') ? new URL(API_BASE).origin : window.location.origin
  const token = getToken()
  if (!token) return origin + pathOrUrl
  const sep = pathOrUrl.includes('?') ? '&' : '?'
  return `${origin}${pathOrUrl}${sep}access_token=${encodeURIComponent(token)}`
}

export function formatTime(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString()
}
