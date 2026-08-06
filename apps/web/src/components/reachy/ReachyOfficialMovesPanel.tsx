/**
 * M24 — Reachy Mini official HF recorded-move library.
 *
 * Two-tab grid showing all moves from the canonical Pollen Robotics
 * HuggingFace datasets:
 *   * pollen-robotics/reachy-mini-emotions-library  (39+ 表情)
 *   * pollen-robotics/reachy-mini-dances-library     (10+ 舞蹈)
 *
 * Playback goes through ReachyMotionPlaybackProvider so random loop and
 * manual clicks share one serial channel.
 */
import { useCallback, useEffect, useState } from 'react'
import {
  AlertTriangle,
  Loader2,
  Music4,
  Play,
  RefreshCw,
  Smile,
} from 'lucide-react'
import { Button } from '../ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../ui/card'
import { Badge } from '../ui/badge'
import {
  listKnownReachyRecordedDatasets,
  listReachyRecordedMoves,
  type ReachyRecordedDataset,
} from '../../lib/reachyApi'
import { useReachyMotionPlayback } from '../../hooks/useReachyMotionPlayback'

interface Props {
  daemonOnline: boolean
}

export function ReachyOfficialMovesPanel({ daemonOnline }: Props) {
  const playback = useReachyMotionPlayback()
  const [datasets, setDatasets] = useState<ReachyRecordedDataset[]>([])
  const [activeKind, setActiveKind] = useState<string>('emotions')
  const [moves, setMoves] = useState<string[]>([])
  const [loadingMoves, setLoadingMoves] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loadingDatasets, setLoadingDatasets] = useState(false)

  const refreshDatasets = useCallback(async () => {
    setLoadingDatasets(true)
    try {
      const r = await listKnownReachyRecordedDatasets()
      setDatasets(r.datasets || [])
    } catch (e) {
      setError(`加载官方数据集列表失败：${(e as Error).message}`)
    } finally {
      setLoadingDatasets(false)
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    const t = window.setTimeout(() => {
      if (cancelled) return
      void refreshDatasets()
    }, 0)
    return () => {
      cancelled = true
      window.clearTimeout(t)
    }
  }, [refreshDatasets])

  const refreshMoves = useCallback(async (dataset: string) => {
    setLoadingMoves(true)
    setError(null)
    try {
      const list = await listReachyRecordedMoves(dataset)
      setMoves(Array.isArray(list) ? list : [])
    } catch (e) {
      setError(`加载动作列表失败：${(e as Error).message}`)
      setMoves([])
    } finally {
      setLoadingMoves(false)
    }
  }, [])

  useEffect(() => {
    const ds = datasets.find((d) => d.kind === activeKind)
    if (!ds) return
    let cancelled = false
    const startup = window.setTimeout(() => {
      if (!cancelled) void refreshMoves(ds.dataset)
    }, 0)
    return () => {
      cancelled = true
      window.clearTimeout(startup)
    }
  }, [activeKind, datasets, refreshMoves])

  const handlePlay = useCallback(async (move: string) => {
    const ds = datasets.find((d) => d.kind === activeKind)
    if (!ds) return
    setError(null)
    try {
      await playback.playRecordedMove({
        dataset: ds.dataset,
        move,
        source: 'manual-official',
      })
    } catch (e) {
      setError(`播放 ${move} 失败：${(e as Error).message}`)
    }
  }, [activeKind, datasets, playback])

  const playingMove = playback.currentSource === 'manual-official' ? playback.currentMove : null

  if (!daemonOnline) {
    return (
      <Card>
        <CardHeader className="py-3 pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            <Music4 className="h-4 w-4" />
            官方动作库
          </CardTitle>
          <CardDescription className="text-xs">HF 表情 + 舞蹈</CardDescription>
        </CardHeader>
        <CardContent className="pt-0">
          <p className="text-xs text-muted-foreground">守护进程未连接，启动后可点播官方动作。</p>
        </CardContent>
      </Card>
    )
  }

  const activeDataset = datasets.find((d) => d.kind === activeKind)

  return (
    <Card>
      <CardHeader className="py-3 pb-2">
        <CardTitle className="text-sm flex items-center gap-2">
          <Music4 className="h-4 w-4" />
          官方动作库
          <Badge variant="outline" className="ml-auto text-[10px]">
            HF · {moves.length} 个
          </Badge>
        </CardTitle>
        <CardDescription className="text-xs">Pollen Robotics 官方表情 + 舞蹈</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 pt-0">
        {/* Tabs */}
        <div className="flex gap-1">
          {datasets.map((d) => (
            <button
              key={d.kind}
              className={`px-2.5 py-1 text-xs rounded-md border transition-colors flex items-center gap-1.5 ${
                activeKind === d.kind
                  ? 'border-[hsl(var(--primary))]/40 bg-[hsl(var(--primary))]/10 text-[hsl(var(--primary))]'
                  : 'border-white/10 text-muted-foreground hover:text-foreground'
              }`}
              onClick={() => setActiveKind(d.kind)}
            >
              {d.kind === 'emotions' ? (
                <Smile className="h-3 w-3" />
              ) : (
                <Music4 className="h-3 w-3" />
              )}
              {d.display_name}
            </button>
          ))}
          <Button
            size="sm"
            variant="ghost"
            className="h-7 px-2 ml-auto"
            onClick={() => void refreshDatasets()}
            disabled={loadingDatasets}
            aria-label="刷新数据集"
          >
            {loadingDatasets ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <RefreshCw className="h-3 w-3" />
            )}
          </Button>
        </div>

        {activeDataset && (
          <p className="text-[10px] text-muted-foreground leading-snug">
            {activeDataset.description} · <span className="font-mono">{activeDataset.dataset}</span>
          </p>
        )}

        {/* Moves grid */}
        {loadingMoves ? (
          <div className="text-center py-6 text-xs text-muted-foreground flex items-center justify-center gap-2">
            <Loader2 className="h-3 w-3 animate-spin" /> 拉取动作中（首次会从 HF 下载索引）…
          </div>
        ) : moves.length === 0 ? (
          <div className="text-center py-6 text-xs text-muted-foreground">没有可播放的动作。</div>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-1.5 max-h-64 overflow-y-auto pr-1">
            {moves.map((m) => (
              <button
                key={m}
                onClick={() => void handlePlay(m)}
                className={`group flex items-center gap-1.5 rounded-md border px-2 py-1.5 text-xs transition-colors ${
                  playingMove === m
                    ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200'
                    : 'border-white/10 hover:border-[hsl(var(--primary))]/40 hover:bg-[hsl(var(--primary))]/5'
                }`}
              >
                {playingMove === m ? (
                  <Loader2 className="h-3 w-3 animate-spin shrink-0" />
                ) : (
                  <Play className="h-3 w-3 shrink-0 opacity-60 group-hover:opacity-100" />
                )}
                <span className="truncate">{m}</span>
              </button>
            ))}
          </div>
        )}

        {error && (
          <div className="rounded-md border border-red-500/30 bg-red-500/5 p-2 text-xs text-red-300 flex items-start gap-2">
            <AlertTriangle className="h-3 w-3 mt-0.5 shrink-0" />
            <span className="break-words">{error}</span>
          </div>
        )}

        <p className="text-[10px] text-muted-foreground">
          随机表演开启时也可随时点击播放；手动点播优先，不会与随机循环打架。
        </p>
      </CardContent>
    </Card>
  )
}
