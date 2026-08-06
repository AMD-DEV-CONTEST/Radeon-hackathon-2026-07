import type {
  AccessSession,
  AnalysisRunAccepted,
  AnalysisRunResponse,
  RunRecord,
  StreamEvent
} from '~/types/api'

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
  const runTransport = computed(() => String(config.public.runTransport || 'stream'))
  let refreshInFlight: Promise<AccessSession> | null = null
  let refreshTimer: ReturnType<typeof setTimeout> | null = null

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
    if (refreshTimer) clearTimeout(refreshTimer)
    refreshTimer = null
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
    else scheduleSessionRefresh()
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
    storeSession(session)
    return session
  }

  function storeSession(session: AccessSession) {
    accessToken.value = session.access_token
    sessionId.value = session.session_id
    sessionExpiresAt.value = Date.parse(session.expires_at)
    if (import.meta.client) {
      sessionStorage.setItem('xianglens-access-token', accessToken.value)
      sessionStorage.setItem('xianglens-session-id', sessionId.value)
      sessionStorage.setItem('xianglens-session-expires-at', String(sessionExpiresAt.value))
    }
    scheduleSessionRefresh()
  }

  function scheduleSessionRefresh() {
    if (!import.meta.client || !accessToken.value) return
    if (refreshTimer) clearTimeout(refreshTimer)
    const refreshAt = sessionExpiresAt.value - 5 * 60_000
    refreshTimer = setTimeout(() => {
      refreshTimer = null
      void refreshSession().catch(() => undefined)
    }, Math.max(1_000, refreshAt - Date.now()))
  }

  async function refreshSession(): Promise<AccessSession> {
    if (refreshInFlight) return await refreshInFlight
    if (!accessToken.value || !sessionId.value) throw new Error('No access session to refresh')
    const currentSessionId = sessionId.value
    refreshInFlight = (async () => {
      const response = await fetch(`${apiBase.value}/api/v1/session/refresh`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${accessToken.value}` }
      })
      if (!response.ok) {
        clearSession()
        throw new Error('The private access session expired. Open a new private session to continue.')
      }
      const session = await response.json() as AccessSession
      if (session.session_id !== currentSessionId) {
        clearSession()
        throw new Error('The API returned a different session identity during refresh')
      }
      storeSession(session)
      return session
    })()
    try {
      return await refreshInFlight
    } finally {
      refreshInFlight = null
    }
  }

  async function ensureFreshSession() {
    if (
      accessToken.value
      && sessionExpiresAt.value <= Date.now() + 5 * 60_000
    ) {
      await refreshSession()
    }
  }

  async function authenticatedFetch(path: string, init: RequestInit = {}): Promise<Response> {
    await ensureFreshSession()
    let response = await fetch(`${apiBase.value}${path}`, {
      ...init,
      headers: headers(init.headers)
    })
    if (response.status === 401 && accessToken.value) {
      await refreshSession()
      response = await fetch(`${apiBase.value}${path}`, {
        ...init,
        headers: headers(init.headers)
      })
    }
    return response
  }

  async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const response = await authenticatedFetch(path, init)
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
    const response = await authenticatedFetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
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

  async function pollRun(
    path: string,
    body: unknown,
    onEvent: (event: StreamEvent) => void
  ): Promise<void> {
    const accepted = await request<AnalysisRunAccepted>(`${path}/async`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    })
    const deadline = Date.now() + 10 * 60 * 1000
    const delay = Math.max(250, Math.min(accepted.poll_after_ms, 5000))
    while (Date.now() < deadline) {
      await new Promise(resolve => setTimeout(resolve, delay))
      const record = await request<RunRecord>(`/api/v1/runs/${accepted.run_id}`)
      if (record.status === 'running') continue
      if ((record.status === 'completed' || record.status === 'blocked') && record.result) {
        onEvent({
          event: 'run.completed',
          data: record.result as AnalysisRunResponse as unknown as Record<string, unknown>
        })
        return
      }
      const detail = record.result && 'error' in record.result
        ? record.result.error
        : undefined
      throw new Error(detail || `Analysis ended with status: ${record.status}`)
    }
    throw new Error('Analysis polling timed out after 10 minutes')
  }

  async function download(path: string): Promise<Blob> {
    const response = await authenticatedFetch(path, {
      method: 'POST',
    })
    if (!response.ok) throw new Error(await response.text())
    return await response.blob()
  }

  return {
    apiBase,
    runTransport,
    accessToken,
    sessionId,
    sessionExpiresAt,
    setApiBase,
    restoreSession,
    openSession,
    refreshSession,
    clearSession,
    request,
    stream,
    pollRun,
    download
  }
}
