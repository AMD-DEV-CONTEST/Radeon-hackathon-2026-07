import { useCallback, useEffect, useRef, useState } from 'react'
import type { JointMap } from '../types/botclaw'

export type CompareState = 'idle' | 'connecting' | 'streaming' | 'done' | 'error'

export interface CompareFrame {
  frame_index: number
  gt: JointMap
  pred: JointMap
  error: JointMap
  step_rmse: number
  latency_ms?: number
  /** M4.4: echo=true 时服务器给出的经安全闸后的可下发关节 */
  safe_pred?: JointMap
  clamped?: string[]
  gate_fatal?: boolean
}

export interface UseCompareOptions {
  modelKey: string
  datasetId: string
  fps?: number
  loop?: boolean
  /** 历史 error 保留多少帧 (滑窗). 默认 600. */
  historyWindow?: number
  /** M4.4: 服务端把 safe_pred 作为 joint_update 广播到 /ws/ui. 默认 false. */
  echo?: boolean
  /** echo 模式下写入 meta.robot_id, 让订阅方分辨 */
  robotId?: string
}

export interface UseCompareReturn {
  state: CompareState
  latest: CompareFrame | null
  totalFrames: number | null
  totalRmse: number | null
  avgStepRmse: number
  errorHistory: CompareFrame[]
  error: string | null
  start: () => void
  stop: () => void
}

function resolveWsUrl(path: string): string {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}${path}`
}

export function useCompareWebSocket(opts: UseCompareOptions): UseCompareReturn {
  const { modelKey, datasetId, fps = 30, loop = false, historyWindow = 600, echo = false, robotId } = opts
  const [state, setState] = useState<CompareState>('idle')
  const [latest, setLatest] = useState<CompareFrame | null>(null)
  const [totalFrames, setTotalFrames] = useState<number | null>(null)
  const [totalRmse, setTotalRmse] = useState<number | null>(null)
  const [errorHistory, setErrorHistory] = useState<CompareFrame[]>([])
  const [err, setErr] = useState<string | null>(null)

  const sumSq = useRef(0)
  const count = useRef(0)
  const wsRef = useRef<WebSocket | null>(null)

  const stop = useCallback(() => {
    const w = wsRef.current
    wsRef.current = null
    if (w) {
      try {
        w.close()
      } catch {
        /* noop */
      }
    }
    setState((s) => (s === 'streaming' || s === 'connecting' ? 'idle' : s))
  }, [])

  const start = useCallback(() => {
    if (wsRef.current) return
    setErr(null)
    setErrorHistory([])
    setLatest(null)
    setTotalRmse(null)
    sumSq.current = 0
    count.current = 0
    setState('connecting')

    const qs = new URLSearchParams({ dataset_id: datasetId, fps: String(fps) })
    if (loop) qs.set('loop', 'true')
    if (echo) qs.set('echo', 'true')
    if (robotId) qs.set('robot_id', robotId)
    const url = resolveWsUrl(`/ws/compare/${encodeURIComponent(modelKey)}?${qs.toString()}`)
    let ws: WebSocket
    try {
      ws = new WebSocket(url)
    } catch (e) {
      setErr((e as Error).message)
      setState('error')
      return
    }
    wsRef.current = ws
    ws.onopen = () => setState('streaming')
    ws.onmessage = (ev) => {
      let msg: unknown
      try {
        msg = JSON.parse(typeof ev.data === 'string' ? ev.data : '')
      } catch {
        return
      }
      const m = msg as Record<string, unknown>
      if (m.type === 'compare_meta') {
        if (typeof m.frame_count === 'number') setTotalFrames(m.frame_count)
        return
      }
      if (m.type === 'compare_done') {
        setTotalRmse(typeof m.total_rmse === 'number' ? m.total_rmse : null)
        setState('done')
        return
      }
      if (m.type === 'error') {
        setErr(String(m.message ?? 'error'))
        setState('error')
        return
      }
      if (m.type === 'compare_frame') {
        const f = m as unknown as CompareFrame
        setLatest(f)
        sumSq.current += f.step_rmse * f.step_rmse
        count.current += 1
        setErrorHistory((prev) => {
          const next = prev.length >= historyWindow ? prev.slice(1) : prev.slice()
          next.push(f)
          return next
        })
      }
    }
    ws.onerror = () => setErr((e) => e ?? 'websocket error')
    ws.onclose = () => {
      wsRef.current = null
    }
  }, [modelKey, datasetId, fps, loop, historyWindow, echo, robotId])

  useEffect(() => {
    return () => {
      const w = wsRef.current
      wsRef.current = null
      if (w) {
        try {
          w.close()
        } catch {
          /* noop */
        }
      }
    }
  }, [])

  const avgStepRmse = count.current > 0 ? Math.sqrt(sumSq.current / count.current) : 0

  return { state, latest, totalFrames, totalRmse, avgStepRmse, errorHistory, error: err, start, stop }
}
