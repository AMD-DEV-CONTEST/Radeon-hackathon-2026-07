import type { StreamEvent } from '~/types/api'

export function useXiangLensApi() {
  const config = useRuntimeConfig()
  const apiKey = useState<string>('xianglens-api-key', () => '')
  const apiBaseOverride = useState<string>('xianglens-api-base', () => '')
  const apiBase = computed(() => {
    const value = apiBaseOverride.value || String(config.public.apiBase)
    return value.trim().replace(/\/$/, '')
  })

  function setApiBase(value: string) {
    apiBaseOverride.value = value.trim().replace(/\/$/, '')
  }

  function headers(input?: HeadersInit): Headers {
    const result = new Headers(input)
    if (apiKey.value) result.set('X-App-API-Key', apiKey.value)
    return result
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

  return { apiBase, apiKey, setApiBase, request, stream, download }
}
