import type { WsEvent } from '@/types'

export interface AuditWsOptions {
  token: string
  documentId: string
  aggressiveness: string
  maxIterations: number
  targetRisk: number
  personas?: string[]
  onEvent: (event: WsEvent) => void
  onClose: () => void
  onError: (err: string) => void
}

export function openAuditSocket(opts: AuditWsOptions): WebSocket {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  const ws = new WebSocket(`${proto}://${location.host}/ws/audit`)

  ws.onopen = () => {
    ws.send(JSON.stringify({
      token: opts.token,
      document_id: opts.documentId,
      aggressiveness: opts.aggressiveness,
      max_iterations: opts.maxIterations,
      target_risk: opts.targetRisk,
      personas: opts.personas,
    }))
  }

  ws.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data) as WsEvent
      opts.onEvent(data)
    } catch {
      // ignore parse errors
    }
  }

  ws.onclose = () => opts.onClose()

  ws.onerror = () => opts.onError('WebSocket connection failed')

  return ws
}
