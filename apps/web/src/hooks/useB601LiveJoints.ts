/**
 * Live follower joints during teleop — WS primary, HTTP fallback, rAF display throttle.
 */
import { useEffect, useRef, useState } from 'react'

import { getB601Joints } from '../lib/b601Api'
import { useRobotRuntimeState } from './useRobotRuntimeState'

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

export function useB601LiveJoints(teleopRunning: boolean) {
  const { joints: wsJoints, connState, error: wsError } = useRobotRuntimeState(
    'b601_rs',
    teleopRunning,
  )
  const [displayJoints, setDisplayJoints] = useState<Record<string, number> | null>(null)
  const latestRef = useRef<Record<string, number> | null>(null)
  const lastGoodRef = useRef<Record<string, number> | null>(null)
  const rafRef = useRef<number | null>(null)

  const wsReady = connState === 'open'
  const wsHasJoints = jointCount(wsJoints) >= 3
  // Only HTTP-fallback while WS not connected or never got joints yet.
  const usePollFallback = teleopRunning && (!wsReady || !wsHasJoints)

  useEffect(() => {
    if (!teleopRunning) {
      latestRef.current = null
      lastGoodRef.current = null
      setDisplayJoints(null)
      return
    }

    const push = (raw: Record<string, number> | null) => {
      if (raw && jointCount(raw) >= 3) {
        lastGoodRef.current = raw
        latestRef.current = raw
      } else if (lastGoodRef.current) {
        latestRef.current = lastGoodRef.current
      }
    }

    push(wsHasJoints ? wsJoints : null)
  }, [teleopRunning, wsJoints, wsHasJoints])

  useEffect(() => {
    if (!usePollFallback) return
    let cancelled = false
    const tick = async () => {
      try {
        const r = await getB601Joints()
        if (!cancelled && r.ok && jointCount(r.joints) >= 3) {
          lastGoodRef.current = r.joints
          latestRef.current = r.joints
        }
      } catch {
        /* retry */
      }
    }
    void tick()
    const t = window.setInterval(() => void tick(), 100)
    return () => {
      cancelled = true
      window.clearInterval(t)
    }
  }, [usePollFallback])

  // rAF throttle — smooth 60fps display even if network is 10–20Hz.
  useEffect(() => {
    if (!teleopRunning) return
    let mounted = true
    const loop = () => {
      if (!mounted) return
      const next = latestRef.current
      if (next) {
        setDisplayJoints((prev) => (jointsNearlyEqual(prev, next) ? prev : { ...next }))
      }
      rafRef.current = requestAnimationFrame(loop)
    }
    rafRef.current = requestAnimationFrame(loop)
    return () => {
      mounted = false
      if (rafRef.current) cancelAnimationFrame(rafRef.current)
    }
  }, [teleopRunning])

  return {
    joints: displayJoints,
    connState,
    wsError,
    usingFallback: usePollFallback,
  }
}
