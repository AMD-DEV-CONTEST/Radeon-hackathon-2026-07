import { useCallback, useEffect, useRef, useState } from 'react'
import { encodeDatasetPath } from '../lib/datasetPath'
import { isJointUpdate, type JointUpdate } from '../types/botclaw'

export type PlaybackState = 'idle' | 'connecting' | 'playing' | 'ended' | 'error'

export interface UsePlaybackOptions {
  datasetId: string
  fps?: number
  loop?: boolean
  onFrame?: (f: JointUpdate) => void
}

export interface UsePlaybackReturn {
  state: PlaybackState
  frameIndex: number
  totalFrames: number | null
  error: string | null
  start: () => void
  stop: () => void
  latest: JointUpdate | null
}

function resolveWsUrl(path: string): string {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}${path}`
}

export function usePlaybackWebSocket(options: UsePlaybackOptions): UsePlaybackReturn {
  const { datasetId, fps = 0, loop = false, onFrame } = options
  const [state, setState] = useState<PlaybackState>('idle')
  const [frameIndex, setFrameIndex] = useState(0)
  const [totalFrames, setTotalFrames] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [latest, setLatest] = useState<JointUpdate | null>(null)

  const wsRef = useRef<WebSocket | null>(null)
  const onFrameRef = useRef<typeof onFrame>(onFrame)
  onFrameRef.current = onFrame

  const stop = useCallback(() => {
    const ws = wsRef.current
    wsRef.current = null
    if (ws && ws.readyState !== WebSocket.CLOSED) {
      try {
        ws.close()
      } catch {
        // ignore
      }
    }
    setState((s) => (s === 'playing' || s === 'connecting' ? 'idle' : s))
  }, [])

  const start = useCallback(() => {
    if (wsRef.current && wsRef.current.readyState <= WebSocket.OPEN) return
    setError(null)
    setFrameIndex(0)
    setState('connecting')

    const qs = new URLSearchParams()
    if (fps > 0) qs.set('fps', String(fps))
    if (loop) qs.set('loop', 'true')
    const url = resolveWsUrl(`/ws/playback/${encodeDatasetPath(datasetId)}?${qs.toString()}`)

    let ws: WebSocket
    try {
      ws = new WebSocket(url)
    } catch (e) {
      setError((e as Error).message)
      setState('error')
      return
    }
    wsRef.current = ws

    ws.onopen = () => setState('playing')
    ws.onmessage = (ev) => {
      let msg: unknown
      try {
        msg = JSON.parse(typeof ev.data === 'string' ? ev.data : '')
      } catch {
        return
      }
      const m = msg as Record<string, unknown>
      if (m.type === 'playback_meta') {
        if (typeof m.frame_count === 'number') setTotalFrames(m.frame_count)
        return
      }
      if (m.type === 'playback_done') {
        setState('ended')
        return
      }
      if (m.type === 'error') {
        setError(String(m.message ?? 'unknown'))
        setState('error')
        return
      }
      if (!isJointUpdate(msg)) return
      const f = msg
      setLatest(f)
      const metaIdx = (f.meta as { frame_index?: number } | undefined)?.frame_index
      if (typeof metaIdx === 'number') {
        setFrameIndex(metaIdx)
      } else {
        setFrameIndex((i) => i + 1)
      }
      onFrameRef.current?.(f)
    }
    ws.onerror = () => setError('websocket error')
    ws.onclose = () => {
      wsRef.current = null
      setState((s) => (s === 'error' ? 'error' : s === 'ended' ? 'ended' : 'idle'))
    }
  }, [datasetId, fps, loop])

  useEffect(() => {
    return () => {
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
  }, [])

  return { state, frameIndex, totalFrames, error, start, stop, latest }
}
