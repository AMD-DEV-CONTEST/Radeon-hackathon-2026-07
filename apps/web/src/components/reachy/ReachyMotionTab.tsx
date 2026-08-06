/**
 * M26 — 动作 Tab.
 *
 * 合并原来散落在多个 Card 的能力：
 *   顶部「随机表演」: 官方库每 10s 随机播放（模块级单例，切 Tab/离开页面仍继续）
 *   上半「我的动作」: custom/*.json 列表 + 单击播放 + 删除
 *   下半「官方库」  : 复用 `ReachyOfficialMovesPanel`（emotions + dances 网格）
 * 录制按钮挪到高级抽屉（ReachyAdvancedDrawer）。
 */
import { useCallback, useEffect, useState } from 'react'
import { Loader2, Play, RefreshCw, Trash2 } from 'lucide-react'
import { Badge } from '../ui/badge'
import { deleteReachyMove, getLocalMoves } from '../../lib/reachyApi'
import { useReachyMotionPlayback } from '../../hooks/useReachyMotionPlayback'
import { ReachyOfficialMovesPanel } from './ReachyOfficialMovesPanel'
import { ReachyRandomMotionPanel } from './ReachyRandomMotionPanel'

interface Props {
  daemonOnline: boolean
}

export function ReachyMotionTab({ daemonOnline }: Props) {
  const playback = useReachyMotionPlayback()
  const [custom, setCustom] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const list = await getLocalMoves('custom')
      setCustom(list)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    const t = window.setTimeout(() => {
      if (cancelled) return
      void refresh()
    }, 0)
    return () => {
      cancelled = true
      window.clearTimeout(t)
    }
  }, [refresh])

  const handlePlay = useCallback(async (name: string) => {
    if (!daemonOnline) {
      setError('机器人未连接')
      return
    }
    setError(null)
    try {
      await playback.playLocalMove({ moveName: name, source: 'manual-custom' })
    } catch (e) {
      setError((e as Error).message)
    }
  }, [daemonOnline, playback])

  const handleDelete = useCallback(async (name: string) => {
    setError(null)
    try {
      await deleteReachyMove('custom', name)
      await refresh()
    } catch (e) {
      setError((e as Error).message)
    }
  }, [refresh])

  const playingCustom = playback.currentSource === 'manual-custom' ? playback.currentMove : null

  return (
    <div className="space-y-3">
      <ReachyRandomMotionPanel daemonOnline={daemonOnline} />

      {/* 我的动作 */}
      <section className="rounded-md border border-white/10 bg-muted/20">
        <div className="flex items-center justify-between border-b border-white/5 px-2.5 py-1.5">
          <div className="flex items-center gap-1.5 text-xs font-medium">
            <Play className="h-3.5 w-3.5 text-sky-300" />
            我的动作
          </div>
          <div className="flex items-center gap-1">
            <Badge variant="outline" className="text-[9px]">{custom.length}</Badge>
            <button
              onClick={() => void refresh()}
              className="rounded p-1 text-muted-foreground hover:bg-white/5 hover:text-foreground"
              title="刷新"
            >
              <RefreshCw className={`h-3 w-3 ${loading ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>
        <div className="p-2 space-y-1 max-h-[260px] overflow-y-auto">
          {custom.length === 0 ? (
            <div className="py-6 text-center text-[11px] text-muted-foreground">
              还没有自定义动作。
              <br />
              高级 → 录制 一个动作后，会出现在这里。
            </div>
          ) : (
            custom.map((name) => (
              <div
                key={name}
                className="flex items-center gap-1.5 rounded-md border border-white/5 bg-white/5 px-2 py-1.5"
              >
                <span className="flex-1 truncate text-xs">{name}</span>
                <button
                  onClick={() => void handlePlay(name)}
                  disabled={!daemonOnline}
                  className="rounded p-1 text-emerald-300 hover:bg-emerald-500/15 disabled:opacity-40"
                  title="播放"
                >
                  {playingCustom === name ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Play className="h-3.5 w-3.5" />
                  )}
                </button>
                <button
                  onClick={() => void handleDelete(name)}
                  className="rounded p-1 text-red-300 hover:bg-red-500/15"
                  title="删除"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            ))
          )}
        </div>
        {error && (
          <div className="border-t border-red-500/20 px-2 py-1 text-[10px] text-red-300">
            {error}
          </div>
        )}
      </section>

      <ReachyOfficialMovesPanel daemonOnline={daemonOnline} />
    </div>
  )
}
