/**
 * Live follower joints during gravity compensation — HTTP ~20Hz + WS + rAF display.
 */
import { useEffect, useRef, useState } from 'react'

import { b601GravityCompStatus } from '../lib/b601Ros2Api'
import { agentWsUrl } from '../lib/localAgent'

function jointCount(j: Record<string, number> | null | undefined): number {
  return j ? Object.keys(j).length : 0
}

function jointsNearlyEqual(
  a: Record<string, number> | null | undefined,
  b: Record<string, number> | null | undefined,
  eps = 0.0015,
): boolean {
  if (!a || !b) return false
  const keys = new Set([...Object.keys(a), ...Object.keys(b)])
  for (const k of keys) {
    if (Math.abs((a[k] ?? 0) - (b[k] ?? 0)) > eps) return false
  }
  return keys.size > 0
}

export function useB601GravityCompLiveJoints(enabled: boolean) {
  const [motorJoints, setMotorJoints] = useState<Record<string, number> | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const latestRef = useRef<Record<string, number> | null>(null)
  const rafRef = useRef<number | null>(null)

  // Primary path: HTTP poll last_state (reads /tmp file — no CAN contention).
  useEffect(() => {
    if (!enabled) {
      latestRef.current = null
      setMotorJoints(null)
      return
    }

    let cancelled = false
    const tick = async () => {
      try {
        const s = await b601GravityCompStatus()
        if (cancelled) return
        const raw = (s.last_state as { joints?: Record<string, number> } | undefined)?.joints
        if (s.running && raw && jointCount(raw) >= 3) {
          latestRef.current = { ...raw }
        }
      } catch {
        /* agent offline */
      }
    }
    void tick()
    const t = window.setInterval(() => void tick(), 50)
    return () => {
      cancelled = true
      window.clearInterval(t)
    }
  }, [enabled])

  // Secondary: WS stream (same data, lower latency when it connects).
  useEffect(() => {
    if (!enabled) {
      wsRef.current?.close()
      wsRef.current = null
      return
    }

    let cancelled = false
    let reconnect: number | null = null

    const connect = () => {
      if (cancelled) return
      const ws = new WebSocket(agentWsUrl('/api/b601/gravity_comp/ws/state'))
      wsRef.current = ws

      ws.onmessage = (event) => {
        if (cancelled) return
        try {
          const data = JSON.parse(event.data as string) as {
            running?: boolean
            state?: { joints?: Record<string, number> }
          }
          if (!data.running) return
          const raw = data.state?.joints
          if (raw && jointCount(raw) >= 3) {
            latestRef.current = { ...raw }
          }
        } catch {
          /* ignore */
        }
      }

      ws.onclose = () => {
        if (!cancelled) {
          reconnect = window.setTimeout(connect, 500)
        }
      }
    }

    connect()
    return () => {
      cancelled = true
      if (reconnect) window.clearTimeout(reconnect)
      wsRef.current?.close()
      wsRef.current = null
    }
  }, [enabled])

  useEffect(() => {
    if (!enabled) return
    let mounted = true
    const loop = () => {
      if (!mounted) return
      const next = latestRef.current
      if (next) {
        setMotorJoints((prev) => (jointsNearlyEqual(prev, next) ? prev : { ...next }))
      }
      rafRef.current = requestAnimationFrame(loop)
    }
    rafRef.current = requestAnimationFrame(loop)
    return () => {
      mounted = false
      if (rafRef.current) cancelAnimationFrame(rafRef.current)
    }
  }, [enabled])

  return { motorJoints }
}
