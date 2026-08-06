/**
 * M4.3 useRobotState — 订阅 /ws/robotstate 的 hook.
 *
 * 返回最新 RobotState 快照 + 连接状态. 订阅者页面直接把它当渲染源.
 */
import { useEffect, useRef, useState } from 'react'

import { resolveRealtimeWsUrl } from '../lib/realtimeOrigin'
import type { RobotState } from '../types/botclaw'

function resolveWsUrl(path: string): string {
  return resolveRealtimeWsUrl(path)
}

export type RobotStateConnState = 'idle' | 'connecting' | 'open' | 'closed' | 'error'

export interface UseRobotStateOptions {
  hz?: number
  robotId?: string
  enabled?: boolean
}

export interface UseRobotStateReturn {
  latest: RobotState | null
  state: RobotStateConnState
  error: string | null
  reconnect: () => void
}

export function useRobotState(opts: UseRobotStateOptions = {}): UseRobotStateReturn {
  const { hz = 2, robotId, enabled = true } = opts
  const [latest, setLatest] = useState<RobotState | null>(null)
  const [state, setState] = useState<RobotStateConnState>('idle')
  const [error, setError] = useState<string | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimer = useRef<number | null>(null)
  const nonceRef = useRef(0)

  useEffect(() => {
    if (!enabled) {
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }
      setState('idle')
      return
    }

    const nonce = ++nonceRef.current
    const qs = new URLSearchParams({ hz: String(hz) })
    if (robotId) qs.set('robot_id', robotId)
    const url = resolveWsUrl(`/ws/robotstate?${qs.toString()}`)

    const open = () => {
      if (nonce !== nonceRef.current) return
      setState('connecting')
      setError(null)
      let ws: WebSocket
      try {
        ws = new WebSocket(url)
      } catch (e) {
        setError(String(e))
        setState('error')
        return
      }
      wsRef.current = ws

      ws.onopen = () => {
        if (nonce !== nonceRef.current) return
        setState('open')
      }
      ws.onmessage = (ev) => {
        if (nonce !== nonceRef.current) return
        try {
          const data = JSON.parse(ev.data)
          if (data && data.type === 'robot_state') {
            setLatest(data as RobotState)
          }
        } catch {
          /* ignore malformed */
        }
      }
      ws.onerror = () => {
        if (nonce !== nonceRef.current) return
        setError('websocket error')
      }
      ws.onclose = () => {
        if (nonce !== nonceRef.current) return
        setState('closed')
        if (reconnectTimer.current) window.clearTimeout(reconnectTimer.current)
        reconnectTimer.current = window.setTimeout(open, 2000)
      }
    }

    open()

    return () => {
      nonceRef.current++
      if (reconnectTimer.current) window.clearTimeout(reconnectTimer.current)
      reconnectTimer.current = null
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }
    }
  }, [hz, robotId, enabled])

  const reconnect = () => {
    nonceRef.current++
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
    setLatest(null)
  }

  return { latest, state, error, reconnect }
}
