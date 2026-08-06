import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, Camera, GitCompareArrows, Play, Square, Gauge, Upload, ExternalLink } from 'lucide-react'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'
import { Badge } from '../components/ui/badge'
import { UrdfViewer } from '../components/features/UrdfViewer'
import { usePlaybackWebSocket } from '../hooks/usePlaybackWebSocket'
import { authJson } from '../lib/auth'
import { encodeDatasetPath } from '../lib/datasetPath'
import type { DatasetSummary, PlaybackMeta } from '../types/dataset'
import type { JointMap } from '../types/botclaw'

const URDF_URL = '/api/urdf/so101.urdf'

function fmt(n: number | null | undefined, digits = 2): string {
  if (n == null || !Number.isFinite(n)) return '—'
  return n.toFixed(digits)
}

export function DatasetDetail() {
  const { datasetId = '' } = useParams()
  const [summary, setSummary] = useState<DatasetSummary | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [joints, setJoints] = useState<Partial<JointMap>>({})
  const [targetFps, setTargetFps] = useState<number>(0)
  const [loop, setLoop] = useState(false)

  const load = useCallback(async () => {
    setErr(null)
    try {
      const enc = encodeDatasetPath(datasetId)
      const [sumRes, metaRes] = await Promise.all([
        fetch(`/api/datasets/${enc}`),
        fetch(`/api/playback/${enc}/meta`),
      ])
      if (!sumRes.ok) throw new Error(`dataset ${sumRes.status}`)
      if (!metaRes.ok) throw new Error(`meta ${metaRes.status}`)
      const s = (await sumRes.json()) as DatasetSummary
      const m = (await metaRes.json()) as PlaybackMeta
      setSummary(s)
      setTargetFps((f) => (f > 0 ? f : Math.round(m.fps_nominal ?? 30)))
    } catch (e) {
      setErr((e as Error).message)
    }
  }, [datasetId])

  useEffect(() => {
    load()
  }, [load])

  const playback = usePlaybackWebSocket({
    datasetId,
    fps: targetFps,
    loop,
    onFrame: (f) => setJoints(f.joints as Partial<JointMap>),
  })

  const progress =
    playback.totalFrames && playback.totalFrames > 0
      ? Math.min(100, (playback.frameIndex / playback.totalFrames) * 100)
      : 0

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2 text-sm">
        <Link to="/datasets" className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground">
          <ArrowLeft className="h-4 w-4" />
          Datasets
        </Link>
        <span className="text-muted-foreground">/</span>
        <span className="font-mono">{datasetId}</span>
        <div className="ml-auto">
          <CompareMenu datasetId={datasetId} />
        </div>
      </div>

      {err && (
        <div className="px-4 py-2 rounded-md bg-red-500/10 border border-red-500/30 text-red-300 text-sm">
          {err}
        </div>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        {/* 3D Playback */}
        <Card className="xl:col-span-2">
          <CardHeader className="flex-row items-center justify-between py-3">
            <CardTitle className="text-base">回放</CardTitle>
            <div className="flex items-center gap-2">
              <Badge variant="outline" className="font-mono text-xs">
                {playback.state}
              </Badge>
              <span className="text-xs text-muted-foreground">
                {playback.frameIndex}
                {playback.totalFrames ? ` / ${playback.totalFrames}` : ''}
              </span>
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className={`grid gap-3 ${summary?.has_images ? 'grid-cols-2' : 'grid-cols-1'}`}>
              <div className="h-[480px] rounded-lg overflow-hidden border bg-black/20">
                <UrdfViewer urdfUrl={URDF_URL} joints={joints} />
              </div>
              {summary?.has_images && (
                <div className="h-[480px] rounded-lg overflow-hidden border bg-black/60 flex items-center justify-center relative">
                  <img
                    src={`/api/datasets/${encodeDatasetPath(datasetId)}/images/cam_main/frame_${String(playback.frameIndex).padStart(6, '0')}.jpg`}
                    alt={`Frame ${playback.frameIndex}`}
                    className="w-full h-full object-contain"
                    onError={(e) => {
                      (e.target as HTMLImageElement).style.display = 'none'
                    }}
                    onLoad={(e) => {
                      (e.target as HTMLImageElement).style.display = 'block'
                    }}
                  />
                  <div className="absolute top-2 left-2 flex items-center gap-1.5 bg-black/60 px-2 py-1 rounded text-xs text-white/80">
                    <Camera className="h-3 w-3" />
                    Frame {playback.frameIndex}
                  </div>
                </div>
              )}
            </div>

            {/* progress */}
            <div className="h-1 bg-muted rounded-full overflow-hidden">
              <div
                className="h-full bg-primary transition-[width] duration-75"
                style={{ width: `${progress}%` }}
              />
            </div>

            <div className="flex flex-wrap items-center gap-3">
              {playback.state === 'playing' ? (
                <Button onClick={playback.stop} variant="destructive" size="sm">
                  <Square className="h-4 w-4 mr-1" />
                  停止
                </Button>
              ) : (
                <Button onClick={playback.start} size="sm">
                  <Play className="h-4 w-4 mr-1" />
                  播放
                </Button>
              )}

              <label className="flex items-center gap-2 text-xs text-muted-foreground">
                <Gauge className="h-3.5 w-3.5" />
                FPS
                <input
                  type="number"
                  min={1}
                  max={200}
                  value={targetFps}
                  onChange={(e) => setTargetFps(Math.max(1, Number(e.target.value) || 30))}
                  className="w-16 px-2 py-1 text-xs rounded border bg-background"
                  disabled={playback.state === 'playing'}
                />
              </label>

              <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <input
                  type="checkbox"
                  checked={loop}
                  onChange={(e) => setLoop(e.target.checked)}
                  disabled={playback.state === 'playing'}
                />
                循环
              </label>

              {playback.error && (
                <span className="text-xs text-red-400">err: {playback.error}</span>
              )}
            </div>
          </CardContent>
        </Card>

        {/* Meta + joint grid */}
        <div className="space-y-4">
          <Card>
            <CardHeader className="py-3">
              <CardTitle className="text-base">元数据</CardTitle>
            </CardHeader>
            <CardContent className="space-y-1.5 text-sm">
              <KV k="Dataset ID" v={<span className="font-mono text-xs">{summary?.dataset_id ?? '—'}</span>} />
              <KV k="Robot" v={summary?.robot_id ?? '—'} />
              <KV k="Source" v={summary?.source ?? '—'} />
              <KV k="帧数" v={summary?.frame_count?.toLocaleString() ?? '—'} />
              <KV k="时长 (s)" v={fmt(summary?.duration_s)} />
              <KV k="FPS (nominal)" v={fmt(summary?.fps_nominal, 1)} />
              <KV k="录制时间" v={summary?.recorded_at ?? '—'} />
              <KV
                k="Path"
                v={<span className="font-mono text-[10px] break-all text-muted-foreground">{summary?.path ?? '—'}</span>}
              />
            </CardContent>
          </Card>

          <PublishToHF datasetId={datasetId} existingRepoId={summary?.hf_repo_id} />

          <Card>
            <CardHeader className="py-3">
              <CardTitle className="text-base">实时关节</CardTitle>
            </CardHeader>
            <CardContent className="grid grid-cols-2 gap-2">
              {(['1', '2', '3', '4', '5', '6'] as const).map((k) => (
                <div key={k} className="px-3 py-2 rounded border bg-muted/20">
                  <div className="text-[10px] text-muted-foreground uppercase tracking-wide">J{k}</div>
                  <div className="font-mono text-sm">{fmt(joints[k])}</div>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}

function KV({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4">
      <span className="text-xs text-muted-foreground">{k}</span>
      <span className="text-right">{v}</span>
    </div>
  )
}

interface HfStatus {
  ok: boolean
  message?: string
  username?: string
}

interface PushResult {
  ok: boolean
  repo_id?: string
  url?: string
  bytes_uploaded?: number
  private?: boolean
  message?: string
  error?: string
}

function PublishToHF({ datasetId, existingRepoId }: { datasetId: string; existingRepoId?: string | null }) {
  const [open, setOpen] = useState(false)
  const [status, setStatus] = useState<HfStatus | null>(null)
  // ``datasetId`` 可能是 ``owner/name`` (Step 4 的 so101-*) 或 ``recording_*``。
  // Repo name 只接受短名 (HF 会拼上 owner)，所以这里把 ``/`` 前的 owner 剥掉，
  // 避免后端把 ``userresu2026/so101-...`` sanitize 成 ``userresu2026-so101-...``。
  const shortName = datasetId.includes('/') ? datasetId.split('/').pop()! : datasetId
  const [repoName, setRepoName] = useState(shortName)
  const [privateRepo, setPrivateRepo] = useState(true)
  const [pushing, setPushing] = useState(false)
  const [result, setResult] = useState<PushResult | null>(null)

  useEffect(() => {
    if (!open || status) return
    ;(async () => {
      try {
        const s = await authJson<HfStatus>('/api/v1/datasets/hf/status')
        setStatus(s)
      } catch (e) {
        setStatus({ ok: false, message: (e as Error).message })
      }
    })()
  }, [open, status])

  const handlePush = async () => {
    setPushing(true)
    setResult(null)
    try {
      // ``datasetId`` 可能是 ``owner/name``。后端路由声明为 ``{dataset_id:path}``，
      // 所以我们只需要把每一段单独做 ``encodeURIComponent``，不能把整个 id
      // 包起来——那样 ``/`` 会变成 ``%2F`` 触发 404。
      const encodedId = datasetId
        .split('/')
        .map((seg) => encodeURIComponent(seg))
        .join('/')
      const r = await authJson<PushResult>(
        `/api/v1/datasets/${encodedId}/push_to_hub`,
        {
          method: 'POST',
          body: JSON.stringify({
            repo_name: repoName || undefined,
            private: privateRepo,
          }),
        },
      )
      setResult(r)
    } catch (e) {
      setResult({ ok: false, error: (e as Error).message })
    } finally {
      setPushing(false)
    }
  }

  // Already pushed — show a compact "view on HF" card instead of the full form.
  if (existingRepoId && !open) {
    return (
      <Card>
        <CardHeader className="py-3">
          <CardTitle className="text-base flex items-center gap-2">
            <Upload className="h-4 w-4" />
            HuggingFace
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          <div className="text-xs text-muted-foreground">已推送到 Hub</div>
          <a
            href={`https://huggingface.co/datasets/${existingRepoId}`}
            target="_blank"
            rel="noreferrer"
            className="font-mono text-xs text-primary underline flex items-center gap-1 break-all"
          >
            {existingRepoId} <ExternalLink className="h-3 w-3 flex-shrink-0" />
          </a>
          <Button variant="outline" size="sm" className="w-full gap-2" onClick={() => setOpen(true)}>
            <Upload className="h-3.5 w-3.5" />
            重新推送 / 覆盖
          </Button>
        </CardContent>
      </Card>
    )
  }

  if (!open) {
    return (
      <Button variant="outline" size="sm" className="w-full gap-2" onClick={() => setOpen(true)}>
        <Upload className="h-4 w-4" />
        Push to HuggingFace
      </Button>
    )
  }

  return (
    <Card>
      <CardHeader className="py-3">
        <CardTitle className="text-base flex items-center gap-2">
          <Upload className="h-4 w-4" />
          Push to HuggingFace
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {status === null ? (
          <div className="text-xs text-muted-foreground">检查 HF token…</div>
        ) : status.ok ? (
          <div className="text-xs text-emerald-300">
            ✓ token 有效 · 推送到 <span className="font-mono">{status.username}</span>
          </div>
        ) : (
          <div className="text-xs text-red-300 bg-red-500/10 border border-red-500/30 rounded px-2 py-1.5">
            HF token 未配置: {status.message}. 在 apps/api/.env 设置 HF_TOKEN 后重启 API.
          </div>
        )}

        <div>
          <label className="text-[11px] uppercase tracking-wide text-muted-foreground">Repo name</label>
          <input
            value={repoName}
            onChange={(e) => setRepoName(e.target.value)}
            className="w-full px-2 py-1.5 rounded border bg-background font-mono text-xs mt-1"
            placeholder="my-dataset"
            disabled={!status?.ok || pushing}
          />
          {status?.ok && status.username && (
            <div className="text-[10px] text-muted-foreground font-mono mt-1">
              → {status.username}/{(repoName || shortName).replace(/^.*\//, '')}
            </div>
          )}
        </div>

        <label className="flex items-center gap-2 text-xs">
          <input
            type="checkbox"
            checked={privateRepo}
            onChange={(e) => setPrivateRepo(e.target.checked)}
            disabled={pushing}
          />
          私有仓库（推荐，实验数据先不公开）
        </label>

        <div className="flex gap-2">
          <Button
            size="sm"
            onClick={handlePush}
            disabled={pushing || !status?.ok || !repoName}
          >
            {pushing ? '推送中…' : 'Push'}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setOpen(false)} disabled={pushing}>
            关闭
          </Button>
        </div>

        {result?.ok && result.url && (
          <div className="text-xs space-y-1">
            <div className="text-emerald-300">✓ {result.message}</div>
            <a
              href={result.url}
              target="_blank"
              rel="noreferrer"
              className="underline flex items-center gap-1 text-primary font-mono break-all"
            >
              {result.repo_id} <ExternalLink className="h-3 w-3 flex-shrink-0" />
            </a>
          </div>
        )}
        {result && !result.ok && (
          <div className="text-xs text-red-400">错误: {result.error}</div>
        )}
      </CardContent>
    </Card>
  )
}

function CompareMenu({ datasetId }: { datasetId: string }) {
  const [open, setOpen] = useState(false)
  const [models, setModels] = useState<
    { model_key: string; dataset_id: string | null; algo: string }[]
  >([])

  useEffect(() => {
    if (!open) return
    ;(async () => {
      try {
        const r = await fetch('/api/inference/models')
        if (!r.ok) return
        const data = (await r.json()) as {
          items: { model_key: string; dataset_id: string | null; algo: string }[]
        }
        setModels(data.items)
      } catch {
        /* ignore */
      }
    })()
  }, [open])

  const compatible = models.filter((m) => m.dataset_id === datasetId)
  const others = models.filter((m) => m.dataset_id !== datasetId)

  return (
    <div className="relative">
      <Button size="sm" variant="outline" onClick={() => setOpen((v) => !v)}>
        <GitCompareArrows className="h-4 w-4 mr-1" />
        Compare 模型
      </Button>
      {open && (
        <div className="absolute right-0 mt-1 w-80 rounded-lg border bg-background shadow-xl z-20 p-2 text-sm">
          <div className="text-[11px] uppercase text-muted-foreground px-2 py-1">同 dataset</div>
          {compatible.length === 0 ? (
            <div className="px-2 py-1.5 text-xs text-muted-foreground">还没有用该 dataset 训练过</div>
          ) : (
            compatible.map((m) => (
              <Link
                key={m.model_key}
                to={`/datasets/${encodeURIComponent(datasetId)}/compare/${encodeURIComponent(m.model_key)}`}
                onClick={() => setOpen(false)}
                className="block px-2 py-1.5 rounded hover:bg-muted font-mono text-xs truncate"
              >
                {m.model_key} <span className="text-muted-foreground">· {m.algo}</span>
              </Link>
            ))
          )}
          {others.length > 0 && (
            <>
              <div className="text-[11px] uppercase text-muted-foreground px-2 py-1 mt-2">其他 (跨 dataset)</div>
              {others.slice(0, 5).map((m) => (
                <Link
                  key={m.model_key}
                  to={`/datasets/${encodeURIComponent(datasetId)}/compare/${encodeURIComponent(m.model_key)}`}
                  onClick={() => setOpen(false)}
                  className="block px-2 py-1.5 rounded hover:bg-muted font-mono text-xs truncate"
                >
                  {m.model_key} <span className="text-muted-foreground">· {m.algo}</span>
                </Link>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  )
}
