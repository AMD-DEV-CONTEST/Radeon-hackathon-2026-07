/**
 * B601 审片 / 清理
 *
 * 一条 = 正面 + 侧面。两路视频常在不同 MP4 文件里，绝对时间轴不同，
 * 必须用「本条相对秒」对齐；3D 用 front 时间轴 + 相对秒 映射录制时的从臂。
 *
 * 主路径仍是录制复位间隙标记/重录；这里偏清理不满意。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { ChevronLeft, ChevronRight, Loader2, Pause, Play, Trash2 } from 'lucide-react'
import { Button } from '../ui/button'
import {
  b601DatasetEpisodeDelete,
  b601DatasetEpisodes,
  b601RecordMark,
  type B601EpisodeItem,
  type B601EpisodeVideo,
} from '../../lib/b601Api'

type Props = {
  repoId: string
  refreshKey?: number
  mode?: 'browse' | 'after-batch'
  onChanged?: (summary: { num_episodes: number; bad_count: number; unmarked_count: number }) => void
  /**
   * Drive 3D from recorded follower state for this episode clock.
   * tFrontGlobal kept for backwards compat; prefer episode_index + t_rel.
   */
  onPlaybackTime?: (
    tFrontGlobal: number,
    meta?: { force?: boolean; episode_index: number; t_rel: number },
  ) => void
  /** Fired when pair playback stops — parent may clear / keep last pose */
  onPlaybackPlayingChange?: (playing: boolean) => void
}

function verdictLabel(v: string | null | undefined) {
  if (v === 'ok') return '可用'
  if (v === 'bad') return '不满意'
  return '未标'
}

function verdictClass(v: string | null | undefined) {
  if (v === 'ok') return 'bg-emerald-500/20 text-emerald-200'
  if (v === 'bad') return 'bg-rose-500/25 text-rose-200'
  return 'bg-white/10 text-muted-foreground'
}

function orderCams(videos: B601EpisodeVideo[]): B601EpisodeVideo[] {
  const rank = (k: string) => {
    const s = k.toLowerCase()
    if (s.includes('front')) return 0
    if (s.includes('side')) return 1
    if (s.includes('top')) return 2
    return 9
  }
  return [...videos].sort((a, b) => rank(a.key) - rank(b.key) || a.key.localeCompare(b.key))
}

function camTitle(key: string) {
  const s = key.toLowerCase()
  if (s.includes('front')) return '正面'
  if (s.includes('side')) return '侧面'
  if (s.includes('top')) return '顶部'
  return key
}

/** Hint browser to the episode slice (same wall-clock segment on both cams). */
function episodeMediaUrl(url: string, from: number, to: number) {
  // Prefer plain URL + JS seek. Media fragments (#t=) are unreliable across browsers
  // for duration / currentTime, which broke paired playback.
  void from
  void to
  return url.split('#')[0]
}

function fmtSec(s: number) {
  const t = Math.max(0, Math.floor(s))
  const m = Math.floor(t / 60)
  const r = t % 60
  return `${m}:${r.toString().padStart(2, '0')}`
}

function windowOf(el: HTMLVideoElement) {
  const from = Number(el.dataset.fromTs || 0)
  const to = Number(el.dataset.toTs || 0)
  const dur = Math.max(0.05, (to || from) - from)
  return { from, to: to || from + dur, dur }
}

function relOf(el: HTMLVideoElement) {
  const { from, dur } = windowOf(el)
  return Math.min(dur, Math.max(0, el.currentTime - from))
}

function seekRel(el: HTMLVideoElement, rel: number) {
  const { from, to, dur } = windowOf(el)
  const clamped = Math.min(dur - 0.04, Math.max(0, rel))
  const target = Math.min(to - 0.04, from + clamped)
  if (Math.abs(el.currentTime - target) > 0.04) el.currentTime = target
}

export function B601EpisodeReview({
  repoId,
  refreshKey = 0,
  mode = 'browse',
  onChanged,
  onPlaybackTime,
  onPlaybackPlayingChange,
}: Props) {
  const [episodes, setEpisodes] = useState<B601EpisodeItem[]>([])
  const [numEpisodes, setNumEpisodes] = useState(0)
  const [badCount, setBadCount] = useState(0)
  const [unmarkedCount, setUnmarkedCount] = useState(0)
  const [selected, setSelected] = useState(0)
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<'all' | 'bad' | 'unmarked'>('unmarked')
  const [epClock, setEpClock] = useState({ rel: 0, dur: 0 })
  const [playing, setPlaying] = useState(false)
  const [playErr, setPlayErr] = useState<string | null>(null)
  const videoRefs = useRef<(HTMLVideoElement | null)[]>([])
  const pairRootRef = useRef<HTMLDivElement>(null)
  const syncing = useRef(false)
  const playingRef = useRef(false)
  /** Ignore pause events caused by seek / programmatic sync */
  const ignorePauseRef = useRef(false)
  const epDurRef = useRef(0)
  /** Front-cam absolute from_timestamp — 3D index is built on this axis */
  const frontFromRef = useRef(0)

  const reload = useCallback(async () => {
    if (!repoId) return
    setLoading(true)
    setError(null)
    try {
      const r = await b601DatasetEpisodes(repoId)
      setEpisodes(r.episodes ?? [])
      setNumEpisodes(r.num_episodes ?? 0)
      setBadCount(r.bad_count ?? 0)
      setUnmarkedCount(r.unmarked_count ?? 0)
      onChanged?.({
        num_episodes: r.num_episodes ?? 0,
        bad_count: r.bad_count ?? 0,
        unmarked_count: r.unmarked_count ?? 0,
      })
      setSelected((prev) => {
        const max = Math.max(0, (r.episodes?.length ?? 1) - 1)
        return Math.min(prev, max)
      })
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }, [onChanged, repoId])

  useEffect(() => {
    void reload()
  }, [reload, refreshKey])

  useEffect(() => {
    setFilter('unmarked')
    setSelected(0)
    setPlayErr(null)
  }, [mode, repoId])

  const filtered = episodes.filter((ep) => {
    if (filter === 'bad') return ep.verdict === 'bad'
    if (filter === 'unmarked') return !ep.verdict
    return true
  })

  const selectedInFilter = Math.min(selected, Math.max(0, filtered.length - 1))
  const current = filtered[selectedInFilter] ?? null
  const cams = current ? orderCams(current.videos || []) : []

  useEffect(() => {
    if (selected >= filtered.length && filtered.length > 0) {
      setSelected(0)
    }
  }, [filter, filtered.length, selected])

  const emitFrontGlobal = useCallback(
    (rel: number, force = false) => {
      const epIdx = current?.episode_index
      if (epIdx == null) {
        onPlaybackTime?.(frontFromRef.current + rel)
        return
      }
      onPlaybackTime?.(frontFromRef.current + rel, {
        force,
        episode_index: epIdx,
        t_rel: rel,
      })
    },
    [current?.episode_index, onPlaybackTime],
  )
  const emitFrontGlobalRef = useRef(emitFrontGlobal)
  emitFrontGlobalRef.current = emitFrontGlobal

  const applyRelToAll = useCallback((rel: number) => {
    syncing.current = true
    ignorePauseRef.current = true
    const vids = pairRootRef.current
      ? ([...pairRootRef.current.querySelectorAll('video')] as HTMLVideoElement[])
      : (videoRefs.current.filter(Boolean) as HTMLVideoElement[])
    for (const el of vids) seekRel(el, rel)
    syncing.current = false
    window.setTimeout(() => {
      ignorePauseRef.current = false
    }, 120)
  }, [])

  // Seek both cams to episode start; snap 3D once.
  // IMPORTANT: do NOT depend on emitFrontGlobal — parent passes inline onPlaybackTime,
  // which would re-run this effect and pause playback on every joint sync tick.
  useEffect(() => {
    if (!current) return
    playingRef.current = false
    setPlaying(false)
    setPlayErr(null)
    const ordered = orderCams(current.videos || [])
    const front = ordered.find((v) => v.key.toLowerCase().includes('front')) ?? ordered[0]
    frontFromRef.current = Number(front?.from_timestamp ?? 0)
    const dur =
      front != null
        ? Math.max(0.05, Number(front.to_timestamp ?? 0) - Number(front.from_timestamp ?? 0))
        : 0
    setEpClock({ rel: 0, dur })
    epDurRef.current = dur

    const id = window.setTimeout(() => {
      ignorePauseRef.current = true
      for (const el of videoRefs.current) {
        if (!el) continue
        el.pause()
        seekRel(el, 0)
      }
      emitFrontGlobalRef.current(0, true)
      window.setTimeout(() => {
        ignorePauseRef.current = false
      }, 120)
    }, 40)
    return () => window.clearTimeout(id)
  }, [current?.episode_index])

  const go = useCallback(
    (delta: number) => {
      if (filtered.length === 0) return
      setSelected((i) => {
        const cur = Math.min(i, filtered.length - 1)
        return (cur + delta + filtered.length) % filtered.length
      })
    },
    [filtered.length],
  )

  const mark = async (verdict: 'ok' | 'bad' | 'clear') => {
    if (!current) return
    setBusy(true)
    setError(null)
    try {
      await b601RecordMark({
        repo_id: repoId,
        episode_index: current.episode_index,
        verdict,
      })
      await reload()
    } catch (e) {
      setError(e instanceof Error ? e.message : '标记失败')
    } finally {
      setBusy(false)
    }
  }

  const deleteOne = async () => {
    if (!current) return
    if (!window.confirm(`删除第 ${current.episode_index + 1} 条？\n正面 + 侧面一起删，不可恢复。`)) return
    setBusy(true)
    setError(null)
    try {
      await b601DatasetEpisodeDelete({
        repo_id: repoId,
        episode_index: current.episode_index,
      })
      await reload()
      setSelected((i) => Math.max(0, Math.min(i, Math.max(0, filtered.length - 2))))
    } catch (e) {
      setError(e instanceof Error ? e.message : '删除失败')
    } finally {
      setBusy(false)
    }
  }

  const deleteAllBad = async () => {
    if (badCount <= 0) return
    if (!window.confirm(`删除全部 ${badCount} 条「不满意」？\n每条含正面+侧面，不可恢复。`)) return
    setBusy(true)
    setError(null)
    try {
      await b601DatasetEpisodeDelete({ repo_id: repoId, delete_all_bad: true })
      await reload()
      setSelected(0)
    } catch (e) {
      setError(e instanceof Error ? e.message : '批量删除失败')
    } finally {
      setBusy(false)
    }
  }

  const collectVideos = useCallback(() => {
    const fromDom = pairRootRef.current
      ? ([...pairRootRef.current.querySelectorAll('video')] as HTMLVideoElement[])
      : []
    if (fromDom.length) return fromDom
    return videoRefs.current.filter(Boolean) as HTMLVideoElement[]
  }, [])

  const pauseBoth = useCallback(() => {
    playingRef.current = false
    setPlaying(false)
    onPlaybackPlayingChange?.(false)
    ignorePauseRef.current = true
    for (const el of collectVideos()) el.pause()
    // Snap 3D to the exact frame under the scrubber (avoid stale mid-pose)
    emitFrontGlobalRef.current(epClock.rel, true)
    window.setTimeout(() => {
      ignorePauseRef.current = false
    }, 80)
  }, [collectVideos, epClock.rel, onPlaybackPlayingChange])

  const playBoth = useCallback(async () => {
    const vids = collectVideos()
    if (!vids.length) {
      setPlayErr('视频还没加载出来，稍等再点。')
      return
    }
    setPlayErr(null)
    const rel = epClock.rel
    applyRelToAll(rel)
    await new Promise((r) => window.setTimeout(r, 100))
    playingRef.current = true
    setPlaying(true)
    onPlaybackPlayingChange?.(true)
    ignorePauseRef.current = true
    const errors: string[] = []
    for (const el of vids) {
      try {
        const p = el.play()
        if (p !== undefined) await p
      } catch (e) {
        errors.push(e instanceof Error ? e.message : String(e))
      }
    }
    window.setTimeout(() => {
      ignorePauseRef.current = false
    }, 250)
    const stillPaused = collectVideos().filter((v) => v.paused)
    if (stillPaused.length) {
      for (const el of stillPaused) {
        try {
          await el.play()
        } catch (e) {
          errors.push(e instanceof Error ? e.message : String(e))
        }
      }
    }
    if (collectVideos().every((v) => v.paused)) {
      playingRef.current = false
      setPlaying(false)
      onPlaybackPlayingChange?.(false)
      setPlayErr(errors[0] ? `播放失败：${errors[0]}` : '播放被打断，请再点一次')
      return
    }
    emitFrontGlobal(rel, true)
  }, [applyRelToAll, collectVideos, emitFrontGlobal, epClock.rel, onPlaybackPlayingChange])

  const togglePlay = () => {
    if (playingRef.current) pauseBoth()
    else void playBoth()
  }

  const scrubTo = (rel: number) => {
    const dur = epClock.dur || 0.05
    const clamped = Math.min(dur, Math.max(0, rel))
    setEpClock((c) => ({ ...c, rel: clamped }))
    applyRelToAll(clamped)
    emitFrontGlobal(clamped, true)
  }

  if (!repoId) return null

  const title = mode === 'browse' ? '看往期' : '本批审片'

  return (
    <div className="space-y-3 rounded-lg border border-white/10 bg-black/20 p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium">{title}</div>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            {numEpisodes} 条 · 不满意 {badCount} · 未标 {unmarkedCount}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="outline" disabled={loading || busy} onClick={() => void reload()}>
            {loading ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : null}
            刷新
          </Button>
          {badCount > 0 && (
            <Button size="sm" variant="destructive" disabled={busy} onClick={() => void deleteAllBad()}>
              <Trash2 className="mr-1 h-3.5 w-3.5" />
              删掉全部不满意
            </Button>
          )}
        </div>
      </div>

      {error && <p className="text-xs text-rose-300 whitespace-pre-wrap">{error}</p>}

      <div className="flex flex-wrap items-center gap-2">
        <div className="flex rounded-md border border-white/10 p-0.5 text-[11px]">
          {(
            [
              ['bad', `不满意 ${badCount}`],
              ['unmarked', `未标 ${unmarkedCount}`],
              ['all', `全部 ${numEpisodes}`],
            ] as const
          ).map(([k, label]) => (
            <button
              key={k}
              type="button"
              className={`rounded px-2 py-1 ${
                filter === k ? 'bg-white/15 text-foreground' : 'text-muted-foreground hover:text-foreground'
              }`}
              onClick={() => {
                setFilter(k)
                setSelected(0)
              }}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {!loading && filter === 'bad' && badCount === 0 && (
        <p className="text-xs text-muted-foreground">没有不满意条目。</p>
      )}

      {filtered.length > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Button size="sm" variant="outline" className="h-9" disabled={filtered.length === 0} onClick={() => go(-1)}>
            <ChevronLeft className="mr-0.5 h-4 w-4" />
            上一条
          </Button>
          <div className="text-center font-mono text-sm tabular-nums">
            {current ? (
              <>
                第 <span className="text-base font-semibold">{current.episode_index + 1}</span> 条
                <span className="text-muted-foreground">
                  {' '}
                  · {selectedInFilter + 1}/{filtered.length}
                </span>
              </>
            ) : (
              '—'
            )}
          </div>
          <Button size="sm" variant="outline" className="h-9" disabled={filtered.length === 0} onClick={() => go(1)}>
            下一条
            <ChevronRight className="ml-0.5 h-4 w-4" />
          </Button>
        </div>
      )}

      {!loading && filtered.length === 0 && filter !== 'bad' && (
        <p className="text-xs text-muted-foreground">这个筛选下没有条目。</p>
      )}

      {current && (
        <div className="space-y-3 rounded-md border border-sky-500/25 bg-sky-950/20 p-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`rounded px-1.5 py-0.5 text-[11px] ${verdictClass(current.verdict as string)}`}>
              {verdictLabel(current.verdict as string)}
            </span>
            {current.length ? (
              <span className="text-[11px] text-muted-foreground">{current.length} 帧</span>
            ) : null}
            <span className="rounded bg-black/40 px-1.5 py-0.5 font-mono text-[11px] text-sky-100">
              本条 {fmtSec(epClock.rel)} / {fmtSec(epClock.dur)}
            </span>
          </div>

          {cams.length > 0 ? (
            <div ref={pairRootRef} className="space-y-2">
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {cams.map((v, i) => {
                  const from = Number(v.from_timestamp ?? 0)
                  const to = Number(v.to_timestamp ?? 0)
                  return (
                    <div
                      key={v.key + v.url + String(current.episode_index)}
                      className="overflow-hidden rounded-md border border-white/10 bg-black/50"
                    >
                      <div className="border-b border-white/10 px-2 py-1 text-[11px] font-medium text-foreground/85">
                        {camTitle(v.key)}
                      </div>
                      <video
                        ref={(el) => {
                          videoRefs.current[i] = el
                        }}
                        className="aspect-video max-h-[220px] w-full bg-black object-contain"
                        src={episodeMediaUrl(v.url, from, to)}
                        playsInline
                        muted
                        preload="auto"
                        data-from-ts={String(from)}
                        data-to-ts={String(to)}
                        onLoadedMetadata={(e) => {
                          seekRel(e.currentTarget, 0)
                        }}
                        onPause={() => {
                          if (ignorePauseRef.current) return
                          if (!playingRef.current) return
                        }}
                        onTimeUpdate={(e) => {
                          if (i !== 0 || syncing.current) return
                          const master = e.currentTarget
                          const dur = epDurRef.current || windowOf(master).dur
                          const rel = relOf(master)
                          // Only stop at real episode end (dur must be meaningful)
                          if (dur > 0.2 && rel >= dur - 0.08) {
                            pauseBoth()
                            applyRelToAll(Math.max(0, dur - 0.05))
                            setEpClock((c) => ({ ...c, rel: dur, dur }))
                            emitFrontGlobal(dur, true)
                            return
                          }
                          if (!playingRef.current) return
                          setEpClock((c) => ({ ...c, rel, dur }))
                          emitFrontGlobal(rel)
                          for (let j = 1; j < videoRefs.current.length; j++) {
                            const other = videoRefs.current[j]
                            if (!other) continue
                            if (Math.abs(relOf(other) - rel) > 0.15) {
                              ignorePauseRef.current = true
                              seekRel(other, rel)
                              window.setTimeout(() => {
                                ignorePauseRef.current = false
                              }, 80)
                            }
                          }
                        }}
                      />
                    </div>
                  )
                })}
              </div>

              {/* 共用一条进度条：只覆盖本条片段 */}
              <div className="flex items-center gap-2 rounded-md border border-white/10 bg-black/40 px-2 py-2">
                <Button
                  type="button"
                  size="sm"
                  variant="secondary"
                  className="h-9 w-9 shrink-0 p-0"
                  onClick={togglePlay}
                  title={playing ? '暂停' : '同步播放正+侧'}
                >
                  {playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
                </Button>
                <input
                  type="range"
                  className="h-2 w-full cursor-pointer accent-sky-400"
                  min={0}
                  max={Math.max(0.05, epClock.dur)}
                  step={0.05}
                  value={Math.min(epClock.rel, epClock.dur || 0)}
                  onChange={(e) => scrubTo(Number(e.target.value))}
                />
                <span className="shrink-0 font-mono text-[11px] tabular-nums text-sky-100">
                  {fmtSec(epClock.rel)} / {fmtSec(epClock.dur)}
                </span>
              </div>
              {playErr && <p className="text-xs text-rose-300">{playErr}</p>}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">本条视频尚未就绪。</p>
          )}

          <Button
            className="h-10 w-full"
            variant="destructive"
            disabled={busy}
            onClick={() => void deleteOne()}
          >
            删除本条
          </Button>
          <details className="text-xs text-muted-foreground">
            <summary className="cursor-pointer select-none hover:text-foreground">改标</summary>
            <div className="mt-2 flex flex-wrap gap-2">
              <Button size="sm" variant="secondary" disabled={busy} onClick={() => void mark('ok')}>
                标可用
              </Button>
              <Button size="sm" variant="secondary" disabled={busy} onClick={() => void mark('bad')}>
                标不满意
              </Button>
              <Button size="sm" variant="outline" disabled={busy} onClick={() => void mark('clear')}>
                撤销标记
              </Button>
            </div>
          </details>
        </div>
      )}

      {badCount > 0 && (
        <p className="text-xs text-amber-200/90">请先删除不满意条目再上传。</p>
      )}
    </div>
  )
}
