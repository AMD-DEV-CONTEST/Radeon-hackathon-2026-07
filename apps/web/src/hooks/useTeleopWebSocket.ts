import { useCallback, useEffect, useRef, useState } from 'react'
import { resolveRealtimeWsUrl } from '../lib/realtimeOrigin'
import { isJointUpdate, type JointUpdate } from '../types/botclaw'

/**
 * /ws/ui (apps/realtime :8002) 的连接状态机.
 *
 *   idle -- connect() --> connecting -- open --> connected
 *     ^                      |                   |
 *     |                      v                   v
 *     +-- disconnect() <-- error <-- close ------+
 */
export type TeleopConnectionState =
  | 'idle'
  | 'connecting'
  | 'connected'
  | 'disconnected'
  | 'error'

export interface UseTeleopWebSocketOptions {
  url?: string
  autoConnect?: boolean
  reconnect?: boolean
  reconnectDelayMs?: number
  onMessage?: (msg: JointUpdate) => void
}

export interface UseTeleopWebSocketReturn {
  state: TeleopConnectionState
  lastUpdate: JointUpdate | null
  fps: number
  error: string | null
  connect: () => void
  disconnect: () => void
}

const DEFAULT_URL = '/ws/ui'

function resolveWsUrl(path: string): string {
  return resolveRealtimeWsUrl(path)
}

export function useTeleopWebSocket(
  options: UseTeleopWebSocketOptions = {},
): UseTeleopWebSocketReturn {
  const {
    url = DEFAULT_URL,
    autoConnect = false,
    reconnect = false,
    reconnectDelayMs = 2000,
    onMessage,
  } = options

  const [state, setState] = useState<TeleopConnectionState>('idle')
  const [lastUpdate, setLastUpdate] = useState<JointUpdate | null>(null)
  const [fps, setFps] = useState(0)
  const [error, setError] = useState<string | null>(null)

  const wsRef = useRef<WebSocket | null>(null)
  const wantOpenRef = useRef<boolean>(false)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const onMessageRef = useRef<typeof onMessage>(onMessage)
  onMessageRef.current = onMessage

  // FPS 计算: 过去 1s 的帧计数
  const frameTimesRef = useRef<number[]>([])

  const clearReconnect = () => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current)
      reconnectTimerRef.current = null
    }
  }

  const disconnect = useCallback(() => {
    wantOpenRef.current = false
    clearReconnect()
    const ws = wsRef.current
    wsRef.current = null
    if (ws && ws.readyState !== WebSocket.CLOSED) {
      try {
        ws.close(1000, 'client-disconnect')
      } catch {
        // ignore
      }
    }
    setState('disconnected')
  }, [])

  const connect = useCallback(() => {
    if (wsRef.current && wsRef.current.readyState <= WebSocket.OPEN) {
      return
    }
    wantOpenRef.current = true
    clearReconnect()
    setError(null)
    setState('connecting')

    let ws: WebSocket
    try {
      ws = new WebSocket(resolveWsUrl(url))
    } catch (e) {
      setError((e as Error).message)
      setState('error')
      return
    }
    wsRef.current = ws

    ws.onopen = () => {
      setState('connected')
    }

    ws.onmessage = (ev) => {
      let parsed: unknown
      try {
        parsed = JSON.parse(typeof ev.data === 'string' ? ev.data : '')
      } catch {
        return
      }
      if (!isJointUpdate(parsed)) return

      const now = performance.now()
      const arr = frameTimesRef.current
      arr.push(now)
      // drop frames older than 1s
      while (arr.length && now - arr[0] > 1000) arr.shift()
      setFps(arr.length)

      setLastUpdate(parsed)
      onMessageRef.current?.(parsed)
    }

    ws.onerror = () => {
      setError('websocket error')
    }

    ws.onclose = () => {
      wsRef.current = null
      if (wantOpenRef.current && reconnect) {
        setState('connecting')
        reconnectTimerRef.current = setTimeout(connect, reconnectDelayMs)
      } else {
        setState((prev) => (prev === 'error' ? 'error' : 'disconnected'))
      }
    }
  }, [url, reconnect, reconnectDelayMs])

  useEffect(() => {
    if (autoConnect) connect()
    return () => {
      wantOpenRef.current = false
      clearReconnect()
      const ws = wsRef.current
      wsRef.current = null
      if (ws) {
        try {
          ws.close()
        } catch {
          // ignore
        }
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return { state, lastUpdate, fps, error, connect, disconnect }
}
