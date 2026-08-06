/**
 * M4.5 Auth — explicit login (localStorage JWT).
 *
 * 替代 M0-M3 期间的 dev-auto-register 自举逻辑. 现在所有调用 authFetch/authJson
 * 的代码都要求用户已通过 /login 获得 token. 没 token 时 authJson 抛 AuthRequiredError,
 * 上层由 AuthProvider / RequireAuth 捕获并跳 /login.
 *
 * 刷新策略: token 失效(401) 时清本地 token 并让上层路由守卫跳登录页 (M4 不做
 * refresh token, Q4=B 的决议).
 */

const TOKEN_KEY = 'botverse.api.token'
const USER_KEY = 'botverse.api.user'

import { readApiError } from './apiError'
import type { Entitlements, SubscriptionTier } from './entitlements'

export interface AuthUser {
  id: string
  username: string
  email: string
  role: string
  permissions: string[]
  is_active: boolean
  subscription_tier?: SubscriptionTier
  tier_expires_at?: string | null
  entitlements?: Entitlements
}

export class AuthRequiredError extends Error {
  constructor(message = 'authentication required') {
    super(message)
    this.name = 'AuthRequiredError'
  }
}

type Listener = (token: string | null, user: AuthUser | null) => void
const listeners: Set<Listener> = new Set()

function emit(): void {
  const t = getToken()
  const u = getUser()
  listeners.forEach((l) => {
    try {
      l(t, u)
    } catch {
      /* noop */
    }
  })
}

export function onAuthChange(cb: Listener): () => void {
  listeners.add(cb)
  return () => {
    listeners.delete(cb)
  }
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function getUser(): AuthUser | null {
  const raw = localStorage.getItem(USER_KEY)
  if (!raw) return null
  try {
    return JSON.parse(raw) as AuthUser
  } catch {
    return null
  }
}

function setToken(token: string | null): void {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
  emit()
}

function setUser(user: AuthUser | null): void {
  if (user) localStorage.setItem(USER_KEY, JSON.stringify(user))
  else localStorage.removeItem(USER_KEY)
  emit()
}

async function fetchJson(path: string, init: RequestInit = {}): Promise<Response> {
  return fetch(path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init.headers || {}),
    },
  })
}

async function fetchMe(token: string): Promise<AuthUser> {
  const r = await fetch('/api/v1/auth/me', {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!r.ok) throw new Error(`fetch /me ${r.status}`)
  return (await r.json()) as AuthUser
}

export async function login(email: string, password: string): Promise<AuthUser> {
  const r = await fetchJson('/api/v1/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })
  if (!r.ok) {
    throw new Error(await readApiError(r, `登录失败 (${r.status})`))
  }
  const data = (await r.json()) as { access_token: string }
  setToken(data.access_token)
  const user = await fetchMe(data.access_token)
  setUser(user)
  return user
}

export async function register(input: {
  username: string
  email: string
  password: string
}): Promise<AuthUser> {
  const r = await fetchJson('/api/v1/auth/register', {
    method: 'POST',
    body: JSON.stringify(input),
  })
  if (!r.ok) {
    throw new Error(await readApiError(r, `注册失败 (${r.status})`))
  }
  const data = (await r.json()) as { access_token: string }
  setToken(data.access_token)
  const user = await fetchMe(data.access_token)
  setUser(user)
  return user
}

export function logout(): void {
  setUser(null)
  setToken(null)
}

/**
 * Refresh cached user from /me, silently clears auth on 401.
 * Call on app boot.
 */
export async function refreshUser(): Promise<AuthUser | null> {
  const t = getToken()
  if (!t) return null
  try {
    const user = await fetchMe(t)
    setUser(user)
    return user
  } catch {
    logout()
    return null
  }
}

export async function authFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const token = getToken()
  if (!token) throw new AuthRequiredError()
  const r = await fetch(input, {
    ...init,
    headers: {
      ...(init.headers || {}),
      Authorization: `Bearer ${token}`,
    },
  })
  if (r.status === 401) {
    markAuthRequired()
    logout()
    throw new AuthRequiredError('token expired')
  }
  return r
}

// ---------------------------------------------------------------------------
// 「登录已过期」全局标记（M51）：401 静默登出让页面悄悄降级，用户不知道为什么
// 少了功能。authFetch 撞 401 时打标记，Layout 挂横幅提示重新登录。
// ---------------------------------------------------------------------------

let authRequiredFlag = false
const authRequiredListeners = new Set<() => void>()

export function isAuthRequired(): boolean {
  return authRequiredFlag
}

export function markAuthRequired(): void {
  authRequiredFlag = true
  for (const cb of authRequiredListeners) cb()
}

export function clearAuthRequired(): void {
  authRequiredFlag = false
  for (const cb of authRequiredListeners) cb()
}

export function onAuthRequired(cb: () => void): () => void {
  authRequiredListeners.add(cb)
  return () => {
    authRequiredListeners.delete(cb)
  }
}

export async function authJson<T>(input: string, init: RequestInit = {}): Promise<T> {
  const r = await authFetch(input, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init.headers || {}),
    },
  })
  if (!r.ok) {
    const text = await r.text().catch(() => '')
    throw new Error(`${r.status} ${text}`.trim())
  }
  return (await r.json()) as T
}

/**
 * Like authJson but works without a token — sends Bearer if available,
 * plain request otherwise.  Use for read endpoints that should be
 * accessible to anonymous visitors.
 */
export async function publicJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken()
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(init.headers as Record<string, string> || {}),
  }
  if (token) headers['Authorization'] = `Bearer ${token}`
  const r = await fetch(path, { ...init, headers })
  if (!r.ok) {
    const text = await r.text().catch(() => '')
    throw new Error(`${r.status} ${text}`.trim())
  }
  return (await r.json()) as T
}

// Backwards-compat helpers — some older callers still use these names.
export function getCachedToken(): string | null {
  return getToken()
}

export function clearToken(): void {
  logout()
}

/**
 * Legacy no-op kept so existing import sites keep compiling during M4.5 rollout.
 * New code should call `login()` explicitly from the Login page.
 */
export async function ensureToken(): Promise<string> {
  const t = getToken()
  if (!t) throw new AuthRequiredError()
  return t
}
