import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Cloud, Database, Film, Gauge, Play, RefreshCw, Video, Zap } from 'lucide-react'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'
import { Badge } from '../components/ui/badge'
import { useAuth } from '../lib/authContext'
import { authJson } from '../lib/auth'
import type { DatasetListResponse, DatasetSummary } from '../types/dataset'

function fmtDuration(s: number | null | undefined): string {
  if (!s || !Number.isFinite(s)) return '—'
  if (s < 60) return `${s.toFixed(2)}s`
  const m = Math.floor(s / 60)
  const r = (s - m * 60).toFixed(1)
  return `${m}m ${r}s`
}

function fmtFps(f: number | null | undefined): string {
  if (!f || !Number.isFinite(f)) return '—'
  return `${f.toFixed(1)} Hz`
}

function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

function readinessLabel(it: DatasetSummary): { text: string; color: string } {
  if (it.hf_repo_id) return { text: '可训练', color: 'border-emerald-500/40 text-emerald-400' }
  if (it.has_images) return { text: '有视频', color: 'border-sky-500/40 text-sky-300' }
  return { text: '仅关节', color: 'border-muted-foreground/40 text-muted-foreground' }
}

export function Datasets() {
  const { token } = useAuth()
  const navigate = useNavigate()
  const [items, setItems] = useState<DatasetSummary[]>([])
  const [total, setTotal] = useState(0)
  const [storageRoot, setStorageRoot] = useState('')
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setErr(null)
    try {
      let apiItems: DatasetSummary[] = []
      let rtItems: DatasetSummary[] = []
      const rtRes = await fetch('/api/datasets')
      if (rtRes.ok) {
        const rt = (await rtRes.json()) as DatasetListResponse
        rtItems = rt.items
        setStorageRoot(rt.storage_root || '')
      }
      if (token) {
        try {
          const api = await authJson<DatasetListResponse>('/api/v1/datasets')
          apiItems = api.items
        } catch {
          apiItems = rtItems
        }
      } else {
        apiItems = rtItems
      }
      const rtById = new Map(rtItems.map((d) => [d.dataset_id, d]))
      const merged: DatasetSummary[] = []
      const seen = new Set<string>()
      for (const it of apiItems) {
        seen.add(it.dataset_id)
        const rt = rtById.get(it.dataset_id)
        const apiFrames = it.frame_count ?? 0
        const rtFrames = rt?.frame_count ?? 0
        const useRtStats = rt && (apiFrames <= 0 || (rtFrames > apiFrames && rt.fps_nominal))
        merged.push(
          useRtStats
            ? {
                ...it,
                frame_count: rt.frame_count,
                duration_s: rt.duration_s ?? it.duration_s,
                fps_nominal: rt.fps_nominal ?? it.fps_nominal,
                has_images: rt.has_images ?? it.has_images,
                recorded_at: rt.recorded_at ?? it.recorded_at,
              }
            : it,
        )
      }
      for (const rt of rtItems) {
        if (!seen.has(rt.dataset_id)) merged.push(rt)
      }
      setItems(merged)
      setTotal(merged.length)
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [token])

  useEffect(() => {
    load()
  }, [load])

  const totalFrames = items.reduce((s, it) => s + (it.frame_count ?? 0), 0)
  const totalDuration = items.reduce((s, it) => s + (it.duration_s ?? 0), 0)

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Datasets</h1>
          <p className="text-muted-foreground mt-1">
            录制的数据集{storageRoot ? <> · <code className="font-mono text-xs">{storageRoot}</code></> : null}
          </p>
        </div>
        <Button onClick={load} disabled={loading} variant="outline">
          <RefreshCw className={`h-4 w-4 mr-2 ${loading ? 'animate-spin' : ''}`} />
          刷新
        </Button>
      </div>

      {err && (
        <div className="px-4 py-2 rounded-md bg-red-500/10 border border-red-500/30 text-red-300 text-sm">
          加载失败: {err}
        </div>
      )}

      {/* Summary */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <SummaryCard icon={<Database className="h-4 w-4" />} label="总数据集" value={total.toString()} />
        <SummaryCard icon={<Film className="h-4 w-4" />} label="累计帧" value={totalFrames.toLocaleString()} />
        <SummaryCard icon={<Gauge className="h-4 w-4" />} label="累计时长" value={fmtDuration(totalDuration)} />
      </div>

      {/* Table */}
      {items.length === 0 ? (
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center justify-center py-16 text-center">
            <Database className="h-12 w-12 text-muted-foreground/40 mb-4" />
            <h3 className="font-semibold text-muted-foreground">还没有数据集</h3>
            <p className="text-sm text-muted-foreground/70 mt-1 max-w-sm">
              去 <Link to="/teleop" className="underline">Teleop</Link> 连一次实时臂并录一段, 数据会自动出现在这里.
            </p>
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardHeader className="py-3">
            <CardTitle className="text-base">数据集列表</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <div className="divide-y">
              {items.map((it) => {
                const { text: statusText, color: statusColor } = readinessLabel(it)
                return (
                  <div
                    key={it.dataset_id}
                    className="flex items-center gap-4 px-4 py-3 hover:bg-muted/40 transition-colors"
                  >
                    <Link
                      to={`/datasets/${encodeURIComponent(it.dataset_id)}`}
                      className="flex-1 min-w-0"
                    >
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-sm truncate">{it.dataset_id}</span>
                        <Badge variant="outline" className={statusColor}>
                          {it.has_images && <Video className="h-3 w-3 mr-0.5" />}
                          {it.hf_repo_id && <Cloud className="h-3 w-3 mr-0.5" />}
                          {statusText}
                        </Badge>
                        {it.robot_id && (
                          <Badge variant="outline" className="text-muted-foreground">
                            {it.robot_id}
                          </Badge>
                        )}
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        {fmtDate(it.recorded_at || (it as Record<string, unknown>).created_at as string | undefined)}
                      </div>
                    </Link>
                    <div className="hidden md:grid grid-cols-3 gap-6 text-xs text-muted-foreground">
                      <Cell label="帧数" v={it.frame_count?.toLocaleString() ?? '—'} />
                      <Cell label="时长" v={fmtDuration(it.duration_s)} />
                      <Cell label="FPS" v={fmtFps(it.fps_nominal)} />
                    </div>
                    {/* Actions */}
                    <div className="flex items-center gap-1.5 shrink-0">
                      {(it.hf_repo_id || it.has_images) && (
                        <Button
                          size="sm"
                          variant="outline"
                          className="h-7 px-2 text-[11px] gap-1"
                          onClick={(e) => {
                            e.preventDefault()
                            navigate(`/training?dataset_id=${encodeURIComponent(it.dataset_id)}&from_setup=1`)
                          }}
                        >
                          <Zap className="h-3 w-3" />
                          训练
                        </Button>
                      )}
                      {it.hf_repo_id && (
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-7 px-2 text-[11px] gap-1 text-muted-foreground"
                          onClick={(e) => {
                            e.preventDefault()
                            navigate(`/inference?dataset_id=${encodeURIComponent(it.dataset_id)}&from_setup=1`)
                          }}
                        >
                          <Play className="h-3 w-3" />
                          推理
                        </Button>
                      )}
                      {!it.hf_repo_id && !it.has_images && (
                        <span className="text-[10px] text-muted-foreground/60">需摄像头</span>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

function SummaryCard({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <Card>
      <CardContent className="py-4">
        <div className="flex items-center gap-2 text-muted-foreground text-xs mb-1">
          {icon}
          <span>{label}</span>
        </div>
        <div className="text-2xl font-semibold font-mono">{value}</div>
      </CardContent>
    </Card>
  )
}

function Cell({ label, v }: { label: string; v: string }) {
  return (
    <div className="text-right">
      <div className="text-[10px] uppercase tracking-wide mb-0.5">{label}</div>
      <div className="font-mono text-foreground">{v}</div>
    </div>
  )
}
