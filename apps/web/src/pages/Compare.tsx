import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { AlertTriangle, ArrowLeft, OctagonX, Play, Radio, Square } from 'lucide-react'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'
import { Badge } from '../components/ui/badge'
import { UrdfViewer } from '../components/features/UrdfViewer'
import { useCompareWebSocket } from '../hooks/useCompareWebSocket'
import type { JointMap } from '../types/botclaw'
import { encodeDatasetPath } from '../lib/datasetPath'

const URDF_URL = '/api/urdf/so101.urdf'
const JOINTS = ['1', '2', '3', '4', '5', '6'] as const

interface LocalModel {
  model_key: string
  algo: string
  dataset_id: string | null
  metrics?: { final_val_rmse_delta?: number } & Record<string, unknown>
}

interface LocalModelsResp {
  items: LocalModel[]
}

function fmt(n: number | null | undefined, digits = 4): string {
  if (n == null || !Number.isFinite(n)) return '—'
  return n.toFixed(digits)
}

export function Compare() {
  const { datasetId = '', modelKey = '' } = useParams()
  const [targetFps, setTargetFps] = useState(30)
  const [loop, setLoop] = useState(false)
  const [echo, setEcho] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [model, setModel] = useState<LocalModel | null>(null)

  useEffect(() => {
    ;(async () => {
      setErr(null)
      try {
        const [dsRes, mRes] = await Promise.all([
          fetch(`/api/datasets/${encodeDatasetPath(datasetId)}`),
          fetch('/api/inference/models'),
        ])
        if (!dsRes.ok) throw new Error(`dataset ${dsRes.status}`)
        if (!mRes.ok) throw new Error(`models ${mRes.status}`)
        const ms = (await mRes.json()) as LocalModelsResp
        const found = ms.items.find((m) => m.model_key === modelKey) ?? null
        setModel(found)
      } catch (e) {
        setErr((e as Error).message)
      }
    })()
  }, [datasetId, modelKey])

  const compare = useCompareWebSocket({
    modelKey,
    datasetId,
    fps: targetFps,
    loop,
    echo,
    robotId: `inference:${modelKey}`,
    historyWindow: 800,
  })

  const gtJoints = useMemo<Partial<JointMap>>(
    () => (compare.latest ? compare.latest.gt : {}),
    [compare.latest],
  )
  const predJoints = useMemo<Partial<JointMap>>(
    () => (compare.latest ? compare.latest.pred : {}),
    [compare.latest],
  )

  const progress =
    compare.totalFrames && compare.totalFrames > 0
      ? Math.min(100, ((compare.latest?.frame_index ?? 0) / compare.totalFrames) * 100)
      : 0

  const onStart = useCallback(() => {
    if (compare.state !== 'streaming' && compare.state !== 'connecting') compare.start()
  }, [compare])

  const onStop = useCallback(() => compare.stop(), [compare])

  const onEstop = useCallback(async () => {
    try {
      await fetch('/api/inference/estop', { method: 'POST' })
    } catch {
      /* noop */
    }
    compare.stop()
  }, [compare])

  const clampedCount = compare.latest?.clamped?.length ?? 0

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 text-sm">
        <Link to={`/datasets/${encodeURIComponent(datasetId)}`} className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground">
          <ArrowLeft className="h-4 w-4" />
          Dataset
        </Link>
        <span className="text-muted-foreground">/</span>
        <span className="font-mono">{datasetId}</span>
        <span className="text-muted-foreground">vs</span>
        <span className="font-mono">{modelKey}</span>
      </div>

      {err && (
        <div className="px-4 py-2 rounded-md bg-red-500/10 border border-red-500/30 text-red-300 text-sm">{err}</div>
      )}

      {/* 双画面 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <Card>
          <CardHeader className="py-2 flex-row items-center justify-between">
            <CardTitle className="text-sm">Ground Truth</CardTitle>
            <Badge variant="outline" className="text-[10px] text-green-300 border-green-500/40">
              录制
            </Badge>
          </CardHeader>
          <CardContent>
            <div className="h-[420px] rounded-lg overflow-hidden border bg-black/20">
              <UrdfViewer urdfUrl={URDF_URL} joints={gtJoints} />
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="py-2 flex-row items-center justify-between">
            <CardTitle className="text-sm">Model Prediction</CardTitle>
            <Badge variant="outline" className="text-[10px] text-sky-300 border-sky-500/40">
              {model?.algo ?? '...'}
            </Badge>
          </CardHeader>
          <CardContent>
            <div className="h-[420px] rounded-lg overflow-hidden border bg-black/20">
              <UrdfViewer urdfUrl={URDF_URL} joints={predJoints} />
            </div>
          </CardContent>
        </Card>
      </div>

      {/* 控制 + 汇总 */}
      <Card>
        <CardContent className="py-3 space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            {compare.state === 'streaming' || compare.state === 'connecting' ? (
              <Button onClick={onStop} variant="destructive" size="sm">
                <Square className="h-4 w-4 mr-1" />
                停止
              </Button>
            ) : (
              <Button onClick={onStart} size="sm">
                <Play className="h-4 w-4 mr-1" />
                开始对比
              </Button>
            )}

            <Badge variant="outline" className="font-mono text-xs">
              {compare.state}
            </Badge>

            <label className="flex items-center gap-2 text-xs text-muted-foreground">
              FPS
              <input
                type="number"
                min={1}
                max={200}
                value={targetFps}
                onChange={(e) => setTargetFps(Math.max(1, Number(e.target.value) || 30))}
                className="w-16 px-2 py-1 text-xs rounded border bg-background"
                disabled={compare.state === 'streaming'}
              />
            </label>

            <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <input type="checkbox" checked={loop} onChange={(e) => setLoop(e.target.checked)} disabled={compare.state === 'streaming'} />
              循环
            </label>

            <label
              className={`flex items-center gap-1.5 text-xs ${echo ? 'text-amber-300' : 'text-muted-foreground'}`}
              title="服务器会把经安全闸后的 pred 作为 joint_update 广播到 /ws/ui, 其他页面的 URDF viewer / 真机 listener 会把它当遥操作帧消费."
            >
              <input
                type="checkbox"
                checked={echo}
                onChange={(e) => setEcho(e.target.checked)}
                disabled={compare.state === 'streaming'}
              />
              <Radio className="h-3.5 w-3.5" />
              Echo to live
            </label>

            {echo && compare.state === 'streaming' && (
              <Button onClick={onEstop} size="sm" variant="destructive" className="bg-red-600 hover:bg-red-700">
                <OctagonX className="h-4 w-4 mr-1" />
                E-Stop
              </Button>
            )}

            <div className="ml-auto flex items-center gap-4 text-xs text-muted-foreground">
              <KV k="Step RMSE" v={fmt(compare.latest?.step_rmse, 5)} />
              <KV k="Avg RMSE" v={fmt(compare.avgStepRmse, 5)} />
              {compare.totalRmse != null && <KV k="Total RMSE" v={fmt(compare.totalRmse, 5)} />}
              <KV k="帧" v={`${compare.latest?.frame_index ?? 0}${compare.totalFrames ? ` / ${compare.totalFrames}` : ''}`} />
              <KV k="latency" v={compare.latest?.latency_ms != null ? `${compare.latest.latency_ms.toFixed(2)}ms` : '—'} />
            </div>
          </div>

          <div className="h-1.5 bg-muted rounded-full overflow-hidden">
            <div className="h-full bg-primary transition-[width] duration-100" style={{ width: `${progress}%` }} />
          </div>

          {compare.error && <div className="text-xs text-red-300">err: {compare.error}</div>}
          {echo && clampedCount > 0 && (
            <div className="text-xs text-amber-300 flex items-center gap-1.5">
              <AlertTriangle className="h-3.5 w-3.5" />
              安全闸触发: {compare.latest?.clamped?.slice(0, 6).join(', ')}
              {clampedCount > 6 && ` ...(${clampedCount} 项)`}
            </div>
          )}
          {compare.latest?.gate_fatal && (
            <div className="text-xs text-red-300 flex items-center gap-1.5">
              <OctagonX className="h-3.5 w-3.5" />
              安全闸已锁定, echo 已停止
            </div>
          )}
        </CardContent>
      </Card>

      {/* 误差时间线 */}
      <Card>
        <CardHeader className="py-2">
          <CardTitle className="text-sm">6 关节误差时间线 (rad)</CardTitle>
        </CardHeader>
        <CardContent>
          <ErrorChart history={compare.errorHistory} />
        </CardContent>
      </Card>

      {/* 6 关节对照表 */}
      <Card>
        <CardHeader className="py-2">
          <CardTitle className="text-sm">实时关节对照</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-2 md:grid-cols-3 gap-2">
          {JOINTS.map((k) => {
            const g = compare.latest?.gt[k]
            const p = compare.latest?.pred[k]
            const e = compare.latest?.error[k]
            return (
              <div key={k} className="px-3 py-2 rounded border bg-muted/20 space-y-1">
                <div className="text-[10px] uppercase text-muted-foreground tracking-wide">J{k}</div>
                <div className="flex justify-between text-xs font-mono">
                  <span className="text-green-300">gt</span>
                  <span>{fmt(g)}</span>
                </div>
                <div className="flex justify-between text-xs font-mono">
                  <span className="text-sky-300">pred</span>
                  <span>{fmt(p)}</span>
                </div>
                <div className="flex justify-between text-xs font-mono">
                  <span className="text-red-300">err</span>
                  <span>{fmt(e)}</span>
                </div>
              </div>
            )
          })}
        </CardContent>
      </Card>
    </div>
  )
}

function KV({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex flex-col leading-tight">
      <span className="text-[10px] uppercase tracking-wide">{k}</span>
      <span className="font-mono text-foreground">{v}</span>
    </div>
  )
}

function ErrorChart({ history }: { history: { frame_index: number; error: JointMap }[] }) {
  if (history.length < 2) {
    return (
      <div className="h-40 rounded border border-dashed flex items-center justify-center text-xs text-muted-foreground">
        开始对比后, 6 关节误差曲线会出现在这里
      </div>
    )
  }

  const W = 800
  const H = 160
  const pad = 20

  // 全局 y 范围
  let minY = Infinity
  let maxY = -Infinity
  for (const h of history) {
    for (const k of JOINTS) {
      const e = h.error[k]
      if (Number.isFinite(e)) {
        if (e < minY) minY = e
        if (e > maxY) maxY = e
      }
    }
  }
  if (!Number.isFinite(minY)) minY = -0.01
  if (!Number.isFinite(maxY)) maxY = 0.01
  const range = Math.max(1e-6, maxY - minY)

  const colors = ['#86efac', '#93c5fd', '#fca5a5', '#fcd34d', '#c4b5fd', '#fda4af']

  const xFor = (i: number) => pad + (i / Math.max(1, history.length - 1)) * (W - 2 * pad)
  const yFor = (v: number) => H - pad - ((v - minY) / range) * (H - 2 * pad)

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-40 rounded border bg-muted/10">
      {/* zero line */}
      <line x1={pad} x2={W - pad} y1={yFor(0)} y2={yFor(0)} stroke="hsl(var(--muted-foreground))" strokeDasharray="2,3" strokeWidth={0.5} />
      {JOINTS.map((k, idx) => {
        const d = history
          .map((h, i) => {
            const v = h.error[k] ?? 0
            return `${i === 0 ? 'M' : 'L'}${xFor(i)},${yFor(v)}`
          })
          .join(' ')
        return <path key={k} d={d} fill="none" stroke={colors[idx]} strokeWidth={1.2} />
      })}
      <text x={pad} y={12} fontSize={10} fill="hsl(var(--muted-foreground))">
        y: [{minY.toFixed(3)}, {maxY.toFixed(3)}] rad  ·  window: {history.length} frames
      </text>
      <g fontSize={10} fontFamily="monospace">
        {JOINTS.map((k, idx) => (
          <g key={k} transform={`translate(${W - pad - 160 + idx * 26}, ${H - 6})`}>
            <rect width={10} height={3} y={-3} fill={colors[idx]} />
            <text x={12} dy="0.1em" fill={colors[idx]}>
              J{k}
            </text>
          </g>
        ))}
      </g>
    </svg>
  )
}
