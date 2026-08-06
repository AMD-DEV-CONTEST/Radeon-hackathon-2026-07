import { useEffect, useRef, useState } from 'react'
import type { TrainingJobDTO } from '../types/training'

function resolveWsUrl(path: string): string {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}${path}`
}

export interface LossPoint {
  epoch: number
  loss: number
}

export interface UseTrainingWsReturn {
  snapshot: TrainingJobDTO | null
  lossHistory: LossPoint[]
  done: boolean
  modelId: string | null
  error: string | null
}

/**
 * 订阅 /ws/trainings/{id} 进度流. 自动累积 loss 时间线.
 * jobId 传 null 时不连.
 */
export function useTrainingWebSocket(jobId: string | null): UseTrainingWsReturn {
  const [snapshot, setSnapshot] = useState<TrainingJobDTO | null>(null)
  const [lossHistory, setLossHistory] = useState<LossPoint[]>([])
  const [done, setDone] = useState(false)
  const [modelId, setModelId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const wsRef = useRef<WebSocket | null>(null)
  const lastEpochRef = useRef<number>(-1)

  useEffect(() => {
    if (!jobId) return
    setSnapshot(null)
    setLossHistory([])
    setDone(false)
    setModelId(null)
    setError(null)
    lastEpochRef.current = -1

    const url = resolveWsUrl(`/ws/trainings/${encodeURIComponent(jobId)}`)
    let ws: WebSocket
    try {
      ws = new WebSocket(url)
    } catch (e) {
      setError((e as Error).message)
      return
    }
    wsRef.current = ws

    ws.onmessage = (ev) => {
      let msg: unknown
      try {
        msg = JSON.parse(typeof ev.data === 'string' ? ev.data : '')
      } catch {
        return
      }
      const m = msg as { type?: string } & TrainingJobDTO & { message?: string; model_id?: string | null }
      if (m.type === 'job_update') {
        setSnapshot(m)
        if (typeof m.loss === 'number' && m.epoch > lastEpochRef.current) {
          lastEpochRef.current = m.epoch
          setLossHistory((prev) => [...prev, { epoch: m.epoch, loss: m.loss as number }])
        }
      } else if (m.type === 'job_done') {
        setDone(true)
        setModelId(m.model_id ?? null)
      } else if (m.type === 'error') {
        setError(m.message ?? 'unknown error')
      }
    }
    ws.onerror = () => setError((e) => e ?? 'websocket error')
    ws.onclose = () => {
      wsRef.current = null
    }

    return () => {
      const w = wsRef.current
      wsRef.current = null
      if (w) {
        try {
          w.close()
        } catch {
          // ignore
        }
      }
    }
  }, [jobId])

  return { snapshot, lossHistory, done, modelId, error }
}
