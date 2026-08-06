/**
 * Subscribe to /ws/robots/{runtimeId}/state — generic runtime state stream.
 */
import { useEffect, useRef, useState } from 'react'

import { agentWsUrl } from '../lib/localAgent'

export interface RobotRuntimeStatePayload {
  type: string
  runtime_id: string
  robot_id?: string
  timestamp: number
  connected?: boolean
  teleop_running?: boolean
  teleop_starting?: boolean
  joints?: Record<string, number>
  health?: Record<string, unknown>
  stream_interval_s?: number
}

export type RobotRuntimeConnState = 'idle' | 'connecting' | 'open' | 'closed' | 'error'

export function useRobotRuntimeState(runtimeId: string, enabled = true) {
  const [payload, setPayload] = useState<RobotRuntimeStatePayload | null>(null)
  const [connState, setConnState] = useState<RobotRuntimeConnState>('idle')
  const [error, setError] = useState<string | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimer = useRef<number | null>(null)
  const attemptRef = useRef(0)

  useEffect(() => {
    if (!enabled) {
      wsRef.current?.close()
      wsRef.current = null
      setConnState('idle')
      return
    }

    let cancelled = false

    const connect = () => {
      if (cancelled) return
      if (wsRef.current?.readyState === WebSocket.OPEN) return
      if (wsRef.current?.readyState === WebSocket.CONNECTING) return

      setConnState('connecting')
      setError(null)

      const ws = new WebSocket(agentWsUrl(`/ws/robots/${encodeURIComponent(runtimeId)}/state`))
      wsRef.current = ws

      ws.onopen = () => {
        if (cancelled) return
        attemptRef.current = 0
        setConnState('open')
        setError(null)
      }

      ws.onmessage = (event) => {
        if (cancelled) return
        try {
          const data = JSON.parse(event.data as string) as RobotRuntimeStatePayload
          if (data.type === 'robot_error') {
            setConnState('error')
            setError((data as { message?: string }).message ?? 'State stream error')
            return
          }
          setPayload((prev) => {
            const prevJ = prev?.joints
            const nextJ = data.joints
            if (
              prev &&
              prev.teleop_running === data.teleop_running &&
              prev.connected === data.connected &&
              prevJ &&
              nextJ &&
              Object.keys(prevJ).length === Object.keys(nextJ).length &&
              Object.keys(nextJ).every(
                (k) => Math.abs((prevJ[k] ?? 0) - (nextJ[k] ?? 0)) < 0.0015,
              )
            ) {
              return prev
            }
            return data
          })
        } catch {
          /* ignore malformed frames */
        }
      }

      ws.onerror = () => {
        if (cancelled) return
        setConnState('error')
        setError('WebSocket error')
      }

      ws.onclose = () => {
        if (cancelled) return
        wsRef.current = null
        setConnState('closed')
        const delay = Math.min(8000, 500 * 2 ** attemptRef.current)
        attemptRef.current += 1
        reconnectTimer.current = window.setTimeout(connect, delay)
      }
    }

    connect()

    return () => {
      cancelled = true
      if (reconnectTimer.current) window.clearTimeout(reconnectTimer.current)
      wsRef.current?.close()
      wsRef.current = null
    }
  }, [runtimeId, enabled])

  return {
    payload,
    joints: payload?.joints ?? null,
    teleopRunning: Boolean(payload?.teleop_running),
    connected: Boolean(payload?.connected),
    connState,
    error,
  }
}
