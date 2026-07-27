import type { AccessSession, StreamEvent } from '~/types/api'

export function useXiangLensApi() {
  const config = useRuntimeConfig()
  const accessToken = useState<string>('xianglens-access-token', () => '')
  const sessionId = useState<string>('xianglens-session-id', () => '')
  const sessionExpiresAt = useState<number>('xianglens-session-expires-at', () => 0)
  const apiBaseOverride = useState<string>('xianglens-api-base', () => '')
  const apiBase = computed(() => {
    const value = apiBaseOverride.value || String(config.public.apiBase)
    return value.trim().replace(/\/$/, '')
  })

  function setApiBase(value: string) {
    const normalized = value.trim().replace(/\/$/, '')
    if (normalized !== apiBase.value) clearSession()
    apiBaseOverride.value = normalized
  }

  function headers(input?: HeadersInit): Headers {
    const result = new Headers(input)
    if (accessToken.value) result.set('Authorization', `Bearer ${accessToken.value}`)
    return result
  }

  function clearSession() {
    accessToken.value = ''
    sessionId.value = ''
    sessionExpiresAt.value = 0
    if (import.meta.client) {
      sessionStorage.removeItem('xianglens-access-token')
      sessionStorage.removeItem('xianglens-session-id')
      sessionStorage.removeItem('xianglens-session-expires-at')
    }
  }

  function restoreSession() {
    if (!import.meta.client) return
    const storedExpiry = Number(sessionStorage.getItem('xianglens-session-expires-at') || 0)
    if (storedExpiry <= Date.now() + 5_000) {
      clearSession()
      return
    }
    accessToken.value = sessionStorage.getItem('xianglens-access-token') || ''
    sessionId.value = sessionStorage.getItem('xianglens-session-id') || ''
    sessionExpiresAt.value = storedExpiry
    if (!accessToken.value || !sessionId.value) clearSession()
  }

  async function openSession(force = false): Promise<AccessSession> {
    if (!force && accessToken.value && sessionId.value && sessionExpiresAt.value > Date.now() + 5_000) {
      return {
        access_token: accessToken.value,
        token_type: 'Bearer',
        expires_in: Math.floor((sessionExpiresAt.value - Date.now()) / 1000),
        expires_at: new Date(sessionExpiresAt.value).toISOString(),
        session_id: sessionId.value
      }
    }
    clearSession()
    const response = await fetch(`${apiBase.value}/api/v1/session`, { method: 'POST' })
    if (!response.ok) {
      const body = await response.json().catch(() => ({ detail: response.statusText }))
      throw new Error(String(body.detail || response.statusText))
    }
    const session = await response.json() as AccessSession
    accessToken.value = session.access_token
    sessionId.value = session.session_id
    sessionExpiresAt.value = Date.parse(session.expires_at)
    if (import.meta.client) {
      sessionStorage.setItem('xianglens-access-token', accessToken.value)
      sessionStorage.setItem('xianglens-session-id', sessionId.value)
      sessionStorage.setItem('xianglens-session-expires-at', String(sessionExpiresAt.value))
    }
    return session
  }

  async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const response = await fetch(`${apiBase.value}${path}`, {
      ...init,
      headers: headers(init.headers)
    })
    if (!response.ok) {
      const body = await response.json().catch(() => ({ detail: response.statusText }))
      throw new Error(String(body.detail || response.statusText))
    }
    if (response.status === 204) return undefined as T
    return await response.json() as T
  }

  async function stream(
    path: string,
    body: unknown,
    onEvent: (event: StreamEvent) => void
  ): Promise<void> {
    const response = await fetch(`${apiBase.value}${path}`, {
      method: 'POST',
      headers: headers({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(body)
    })
    if (!response.ok || !response.body) {
      const message = await response.text()
      throw new Error(message || response.statusText)
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    while (true) {
      const { done, value } = await reader.read()
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
      const blocks = buffer.split('\n\n')
      buffer = blocks.pop() || ''
      for (const block of blocks) {
        const event = block.split('\n').find(line => line.startsWith('event: '))?.slice(7)
        const data = block.split('\n').find(line => line.startsWith('data: '))?.slice(6)
        if (event && data) onEvent({ event, data: JSON.parse(data) })
      }
      if (done) break
    }
  }

  async function download(path: string): Promise<Blob> {
    const response = await fetch(`${apiBase.value}${path}`, {
      method: 'POST',
      headers: headers()
    })
    if (!response.ok) throw new Error(await response.text())
    return await response.blob()
  }

  return {
    apiBase,
    accessToken,
    sessionId,
    sessionExpiresAt,
    setApiBase,
    restoreSession,
    openSession,
    clearSession,
    request,
    stream,
    download
  }
}
