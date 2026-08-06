import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Activity, AlertTriangle, Cpu, Play, Radio, Square, Upload, Zap } from 'lucide-react'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'
import { Badge } from '../components/ui/badge'
import { useAuth } from '../lib/authContext'
import { authJson } from '../lib/auth'

/**
 * M8.3 — Vision-conditioned live inference page.
 *
 * This page is the UI counterpart of `apps/realtime/api/vision_inference.py`:
 *
 *   - GET  /api/vision_inference/status            (poll every 2s when not streaming)
 *   - POST /api/vision_inference/load              (model_key + prefer_device)
 *   - POST /api/vision_inference/unload
 *   - POST /api/vision_inference/bootstrap_stub    (dev-only helper)
 *   - POST /api/vision_inference/estop
 *   - WS   /ws/vision_inference?camera_device=0&fps=15&echo=<bool>
 *
 * The device badge is the important bit — we surface the full device-probe
 * result from the backend so the user sees at a glance whether we're on CPU
 * (with a ROCm fallback reason) or on a working GPU.
 */

type DeviceStatus = {
  requested: string
  resolved: 'cpu' | 'cuda' | string
  cuda_advertised: boolean
  cuda_usable: boolean
  probe_error: string | null
  device_name: string | null
}

type Status = {
  loaded: boolean
  model_key: string | null
  kind?: string | null
  task_prompt?: string | null
  prediction_mode: string | null
  device: DeviceStatus
  active_ws: number
  loaded_at: number | null
  global_estop: boolean
  estop_reason: string | null
  pi0_predict_health?: {
    consecutive_failures: number
    breaker_open: boolean
    breaker_open_until: number | null
    breaker_remaining_s: number
  }
}

type ModelListItem = {
  model_key: string
  algo?: string
  dataset_id?: string | null
  metrics?: Record<string, unknown>
  hparams?: Record<string, unknown>
  path?: string
}

type FrameMsg = {
  type: 'vision_infer_frame'
  frame_index: number
  latency_ms: number
  joint_state: Record<string, number>
  pred: Record<string, number>
  safe_pred: Record<string, number>
  clamped: string[]
  gate_fatal: boolean
  image_feature_l2: number
  device: string
}

type MetaMsg = {
  type: 'vision_infer_meta'
  model_key: string
  device: DeviceStatus
  fps: number
  echo: boolean
  prediction_mode: string
}

const JOINT_LABELS: Record<string, string> = {
  '1': 'shoulder_pan',
  '2': 'shoulder_lift',
  '3': 'elbow_flex',
  '4': 'wrist_flex',
  '5': 'wrist_roll',
  '6': 'gripper',
}

function useStatusPoll(enabled: boolean) {
  const [status, setStatus] = useState<Status | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    if (!enabled) return
    let cancelled = false
    async function load() {
      try {
        const r = await fetch('/api/vision_inference/status?prefer=cpu')
        if (!r.ok) throw new Error(`status ${r.status}`)
        const s = (await r.json()) as Status
        if (!cancelled) {
          setStatus(s)
          setErr(null)
        }
      } catch (e) {
        if (!cancelled) setErr(String(e))
      }
    }
    load()
    const id = setInterval(load, 2000)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [enabled])

  return { status, err, refresh: () => fetch('/api/vision_inference/status?prefer=cpu').then((r) => r.json()).then(setStatus).catch((e) => setErr(String(e))) }
}

function DeviceBadge({ device }: { device: DeviceStatus | undefined }) {
  if (!device) {
    return <Badge variant="outline">device: unknown</Badge>
  }
  const gpuOk = device.resolved === 'cuda' && device.cuda_usable
  const cpuFallback = device.resolved === 'cpu' && device.cuda_advertised
  return (
    <div className="flex items-center gap-2">
      <Badge
        variant="outline"
        className={
          gpuOk
            ? 'border-green-500/50 text-green-400'
            : cpuFallback
              ? 'border-amber-500/50 text-amber-400'
              : 'border-muted-foreground/40 text-muted-foreground'
        }
      >
        {gpuOk ? (
          <><Zap className="h-3 w-3 mr-1" />GPU ({device.device_name})</>
        ) : (
          <><Cpu className="h-3 w-3 mr-1" />CPU{cpuFallback ? ' (GPU fallback)' : ''}</>
        )}
      </Badge>
      {cpuFallback && device.probe_error && (
        <span
          className="text-xs text-amber-400/80 truncate max-w-[320px]"
          title={device.probe_error}
        >
          {device.probe_error.split('\n')[0]}
        </span>
      )}
    </div>
  )
}

export function Inference() {
  const { token } = useAuth()
  const setupParams = useMemo(() => {
    const params = new URLSearchParams(window.location.search)
    return {
      modelKey: params.get('model_key')?.trim() ?? '',
      datasetId: params.get('dataset_id')?.trim() ?? '',
      fromSetup: params.get('from_setup') === '1',
    }
  }, [])
  const { status, err: statusErr, refresh: refreshStatus } = useStatusPoll(true)
  const [models, setModels] = useState<ModelListItem[]>([])
  const [selected, setSelected] = useState<string>('')
  const [customModelKey, setCustomModelKey] = useState<string>(setupParams.modelKey || '')
  const [useCustom, setUseCustom] = useState<boolean>(!setupParams.modelKey ? true : true)
  const [taskPrompt, setTaskPrompt] = useState<string>('pick up the object')
  const [preferDevice, setPreferDevice] = useState<'auto' | 'cpu' | 'cuda'>('cpu')
  const [cameraDevice, setCameraDevice] = useState<string>('0')
  const [fps, setFps] = useState<number>(15)
  const [echoToUi, setEchoToUi] = useState<boolean>(false)
  const [busy, setBusy] = useState<boolean>(false)
  const [actionMsg, setActionMsg] = useState<string | null>(null)

  // streaming state
  const [streaming, setStreaming] = useState<boolean>(false)
  const [lastFrame, setLastFrame] = useState<FrameMsg | null>(null)
  const [meta, setMeta] = useState<MetaMsg | null>(null)
  const [framesRx, setFramesRx] = useState<number>(0)
  const [wsErr, setWsErr] = useState<string | null>(null)
  const [latencyAvg, setLatencyAvg] = useState<number>(0)
  const wsRef = useRef<WebSocket | null>(null)
  const latencyBufRef = useRef<number[]>([])

  // Load available models + auto-resolve from latest training job
  useEffect(() => {
    let cancelled = false
    fetch('/api/inference/models')
      .then((r) => r.json())
      .then((data) => {
        if (cancelled) return
        const items: ModelListItem[] = data.items ?? []
        setModels(items)
        const linkedLocal = setupParams.modelKey
          ? items.find((m) => m.model_key === setupParams.modelKey)
          : null
        if (linkedLocal) {
          setSelected(linkedLocal.model_key)
          setUseCustom(false)
        } else if (!selected && items.length > 0) {
          setSelected(items[0].model_key)
        }
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [selected, setupParams.modelKey])

  // Auto-resolve model key from latest succeeded Qualia training job
  useEffect(() => {
    if (setupParams.modelKey || !token) return
    let cancelled = false
    authJson<{ items: { status: string; hparams: Record<string, unknown> }[] }>('/api/v1/trainings')
      .then((data) => {
        if (cancelled) return
        const succeeded = data.items?.find((j) => j.status === 'succeeded')
        if (!succeeded) return
        const hp = succeeded.hparams || {}
        const outputModel = hp.output_model_id as string | undefined
        if (outputModel && !customModelKey) {
          setCustomModelKey(outputModel)
          setUseCustom(true)
        }
      })
      .catch(() => {})
    return () => { cancelled = true }
  }, [token, setupParams.modelKey, customModelKey])

  const postJson = useCallback(async (path: string, body?: unknown) => {
    setBusy(true)
    setActionMsg(null)
    try {
      const r = await fetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: body === undefined ? '{}' : JSON.stringify(body),
      })
      const data = await r.json().catch(() => ({}))
      if (!r.ok) {
        const detail = (data && (data.detail || data.message)) || `${r.status}`
        throw new Error(String(detail))
      }
      setActionMsg(`${path.split('/').pop()} OK`)
      await refreshStatus()
      return data
    } catch (e) {
      setActionMsg(`${path.split('/').pop()} failed: ${String(e)}`)
      throw e
    } finally {
      setBusy(false)
    }
  }, [refreshStatus])

  const doLoad = useCallback(async () => {
    const key = useCustom ? customModelKey.trim() : selected
    if (!key) {
      setActionMsg('pick a model first')
      return
    }
    await postJson('/api/vision_inference/load', {
      model_key: key,
      prefer_device: preferDevice,
      task_prompt: taskPrompt,
    })
  }, [useCustom, customModelKey, selected, preferDevice, taskPrompt, postJson])

  const doUnload = useCallback(async () => {
    await postJson('/api/vision_inference/unload')
  }, [postJson])

  const doBootstrap = useCallback(async () => {
    const data = await postJson('/api/vision_inference/bootstrap_stub', { model_key: 'vision_stub_demo' })
    // refresh model list
    const r = await fetch('/api/inference/models')
    const list = await r.json()
    setModels(list.items ?? [])
    if (data?.model_key) setSelected(data.model_key)
  }, [postJson])

  const doEstop = useCallback(async () => {
    await postJson('/api/vision_inference/estop')
  }, [postJson])

  const startStream = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
    if (!status?.loaded) {
      setWsErr('no model loaded — click Load first')
      return
    }
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const qs = new URLSearchParams({
      camera_device: cameraDevice,
      fps: String(fps),
      echo: String(echoToUi),
    })
    const url = `${proto}//${window.location.host}/ws/vision_inference?${qs}`
    const ws = new WebSocket(url)
    wsRef.current = ws
    setStreaming(true)
    setWsErr(null)
    setFramesRx(0)
    latencyBufRef.current = []
    ws.onmessage = (ev) => {
      try {
        const m = JSON.parse(ev.data)
        if (m.type === 'vision_infer_meta') {
          setMeta(m as MetaMsg)
        } else if (m.type === 'vision_infer_frame') {
          setLastFrame(m as FrameMsg)
          setFramesRx((n) => n + 1)
          const buf = latencyBufRef.current
          buf.push(Number(m.latency_ms) || 0)
          if (buf.length > 60) buf.shift()
          const avg = buf.reduce((a, b) => a + b, 0) / Math.max(1, buf.length)
          setLatencyAvg(avg)
        } else if (m.type === 'error') {
          setWsErr(String(m.message))
        }
      } catch (e) {
        setWsErr(`parse error: ${String(e)}`)
      }
    }
    ws.onerror = () => setWsErr('WebSocket error')
    ws.onclose = () => {
      setStreaming(false)
      wsRef.current = null
    }
  }, [cameraDevice, fps, echoToUi, status])

  const stopStream = useCallback(() => {
    wsRef.current?.close()
    wsRef.current = null
    setStreaming(false)
  }, [])

  useEffect(() => {
    return () => {
      wsRef.current?.close()
    }
  }, [])

  const mjpegSrc = useMemo(
    () => `/api/camera/mjpeg?device=${encodeURIComponent(cameraDevice)}&fps=${fps}&quality=70`,
    [cameraDevice, fps],
  )

  const jointKeys = ['1', '2', '3', '4', '5', '6']

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Live Inference</h1>
        <p className="text-muted-foreground">
          Vision-conditioned policy rollout. Camera + current joint state → predicted action, clamped
          through the safety gate before touching any follower.
        </p>
      </div>

      {setupParams.fromSetup && (
        <div className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-sm text-emerald-200">
          已从 SO-101 引导带入
          {setupParams.modelKey && (
            <>
              {' '}模型 <code className="font-mono">{setupParams.modelKey}</code>
            </>
          )}
          {setupParams.datasetId && (
            <>
              {' '}和数据集 <code className="font-mono">{setupParams.datasetId}</code>
            </>
          )}
          。确认安全后先 Load，再开始推理。
        </div>
      )}

      {/* ---------- status card ---------- */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-base flex items-center gap-2">
            <Activity className="h-4 w-4" /> Runtime Status
          </CardTitle>
          <DeviceBadge device={status?.device} />
        </CardHeader>
        <CardContent className="text-sm space-y-2">
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            <div>
              <div className="text-xs text-muted-foreground">Model</div>
              <div className="font-mono truncate">{status?.model_key ?? '—'}</div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">Policy kind</div>
              <div className="font-mono">{status?.kind ?? '—'}</div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">Prediction mode</div>
              <div>{status?.prediction_mode ?? '—'}</div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">Active WS</div>
              <div>{status?.active_ws ?? 0}</div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">Global E-Stop</div>
              <div className={status?.global_estop ? 'text-red-400' : ''}>
                {status?.global_estop ? `YES (${status.estop_reason ?? 'unknown'})` : 'no'}
              </div>
            </div>
          </div>
          {status?.pi0_predict_health && (
            <div className="text-xs text-muted-foreground">
              Pi0 predict health: failures={status.pi0_predict_health.consecutive_failures}
              {status.pi0_predict_health.breaker_open
                ? ` · breaker open (${status.pi0_predict_health.breaker_remaining_s.toFixed(1)}s)`
                : ' · breaker closed'}
            </div>
          )}
          {statusErr && <div className="text-xs text-red-400">status error: {statusErr}</div>}
          {actionMsg && <div className="text-xs text-muted-foreground">{actionMsg}</div>}
        </CardContent>
      </Card>

      {/* ---------- model pick + controls ---------- */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base flex items-center gap-2">
            <Upload className="h-4 w-4" /> Model & Device
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center gap-4 text-xs">
            <label className="flex items-center gap-2 cursor-pointer">
              <input type="radio" checked={useCustom} onChange={() => setUseCustom(true)} />
              <span>
                HF repo — ACT or Pi0 (e.g. <code>qualia-robotics/act-so101-...</code>)
              </span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <input type="radio" checked={!useCustom} onChange={() => setUseCustom(false)} />
              <span>Local model</span>
            </label>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {useCustom ? (
              <label className="text-xs text-muted-foreground flex flex-col gap-1 md:col-span-2">
                <span>HF repo id</span>
                <input
                  value={customModelKey}
                  onChange={(e) => setCustomModelKey(e.target.value)}
                  placeholder="qualia-robotics/act-so101-20260422-0445-1b35f73c"
                  className="bg-background border border-border rounded px-2 py-1 text-sm font-mono"
                />
              </label>
            ) : (
              <label className="text-xs text-muted-foreground flex flex-col gap-1 md:col-span-2">
                <span>Local model</span>
                <select
                  value={selected}
                  onChange={(e) => setSelected(e.target.value)}
                  className="bg-background border border-border rounded px-2 py-1 text-sm"
                >
                  {models.length === 0 ? (
                    <option value="">(no local models)</option>
                  ) : (
                    models.map((m) => (
                      <option key={m.model_key} value={m.model_key}>
                        {m.model_key}
                        {m.algo ? ` — ${m.algo}` : ''}
                      </option>
                    ))
                  )}
                </select>
              </label>
            )}
            <label className="text-xs text-muted-foreground flex flex-col gap-1">
              <span>Prefer device</span>
              <select
                value={preferDevice}
                onChange={(e) => setPreferDevice(e.target.value as 'auto' | 'cpu' | 'cuda')}
                className="bg-background border border-border rounded px-2 py-1 text-sm"
              >
                <option value="auto">auto</option>
                <option value="cpu">cpu</option>
                <option value="cuda">cuda</option>
              </select>
            </label>
          </div>

          {useCustom && (
            <label className="text-xs text-muted-foreground flex flex-col gap-1">
              <span>Task prompt (Pi0 / VLA)</span>
              <input
                value={taskPrompt}
                onChange={(e) => setTaskPrompt(e.target.value)}
                placeholder="pick up the object"
                className="bg-background border border-border rounded px-2 py-1 text-sm"
              />
            </label>
          )}

          <div className="flex items-center gap-2">
            <Button size="sm" disabled={busy} onClick={doLoad}>
              Load
            </Button>
            <Button size="sm" variant="outline" disabled={busy || !status?.loaded} onClick={doUnload}>
              Unload
            </Button>
            <Button size="sm" variant="ghost" disabled={busy} onClick={doBootstrap}>
              Create stub
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* ---------- live inference ---------- */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card className="lg:col-span-2 overflow-hidden">
          <CardHeader className="pb-2 flex flex-row items-center justify-between space-y-0">
            <CardTitle className="text-base flex items-center gap-2">
              <Radio className="h-4 w-4" /> Camera → Policy
            </CardTitle>
            <div className="flex items-center gap-2">
              <Badge variant="outline">{streaming ? 'streaming' : 'idle'}</Badge>
              {streaming && (
                <Badge variant="outline">
                  {framesRx} frames · avg {latencyAvg.toFixed(1)} ms · last {lastFrame?.device ?? '?'}
                </Badge>
              )}
            </div>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="aspect-video rounded-lg overflow-hidden border bg-black/60 flex items-center justify-center">
              {streaming ? (
                <img src={mjpegSrc} alt="camera" className="w-full h-full object-contain" />
              ) : (
                <div className="text-xs text-muted-foreground">camera preview will appear when streaming</div>
              )}
            </div>

            <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
              <label className="text-xs text-muted-foreground flex flex-col gap-1">
                <span>Camera /dev/videoN</span>
                <input
                  type="text"
                  value={cameraDevice}
                  onChange={(e) => setCameraDevice(e.target.value)}
                  disabled={streaming}
                  className="bg-background border border-border rounded px-2 py-1 text-sm"
                />
              </label>
              <label className="text-xs text-muted-foreground flex flex-col gap-1">
                <span>FPS</span>
                <input
                  type="number"
                  value={fps}
                  min={1}
                  max={30}
                  onChange={(e) => setFps(Number(e.target.value))}
                  disabled={streaming}
                  className="bg-background border border-border rounded px-2 py-1 text-sm"
                />
              </label>
              <label className="text-xs text-muted-foreground flex items-center gap-2 mt-5">
                <input
                  type="checkbox"
                  checked={echoToUi}
                  onChange={(e) => setEchoToUi(e.target.checked)}
                  disabled={streaming}
                />
                Echo to /ws/ui (URDF + follower)
              </label>
              <div className="flex items-end gap-2">
                {streaming ? (
                  <Button size="sm" variant="destructive" onClick={stopStream}>
                    <Square className="h-4 w-4 mr-1" />Stop
                  </Button>
                ) : (
                  <Button size="sm" onClick={startStream} disabled={!status?.loaded}>
                    <Play className="h-4 w-4 mr-1" />Start
                  </Button>
                )}
                <Button size="sm" variant="outline" onClick={doEstop} disabled={busy}>
                  <AlertTriangle className="h-4 w-4 mr-1" />E-Stop
                </Button>
              </div>
            </div>

            {wsErr && <div className="text-xs text-red-400">{wsErr}</div>}
            {meta && (
              <div className="text-xs text-muted-foreground">
                meta: model={meta.model_key} · fps={meta.fps} · mode={meta.prediction_mode} · echo={String(meta.echo)}
              </div>
            )}
          </CardContent>
        </Card>

        {/* ---------- joints panel ---------- */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Action Predictions</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {jointKeys.map((k) => {
              const obs = lastFrame?.joint_state?.[k] ?? 0
              const pred = lastFrame?.pred?.[k] ?? 0
              const safe = lastFrame?.safe_pred?.[k] ?? 0
              const clamped = (lastFrame?.clamped ?? []).some((c) => c.startsWith(`${k}:`))
              return (
                <div key={k} className="text-xs space-y-0.5">
                  <div className="flex justify-between">
                    <span className="font-mono text-muted-foreground">
                      j{k} <span className="text-muted-foreground/70">{JOINT_LABELS[k]}</span>
                    </span>
                    {clamped && <span className="text-amber-400">clamped</span>}
                  </div>
                  <div className="flex gap-2 font-mono tabular-nums">
                    <span className="w-1/3 truncate" title={`obs ${obs.toFixed(4)}`}>obs  {obs.toFixed(3)}</span>
                    <span className="w-1/3 truncate" title={`pred ${pred.toFixed(4)}`}>pred {pred.toFixed(3)}</span>
                    <span className="w-1/3 truncate" title={`safe ${safe.toFixed(4)}`}>safe {safe.toFixed(3)}</span>
                  </div>
                </div>
              )
            })}
            {lastFrame && (
              <div className="pt-2 mt-2 border-t text-xs text-muted-foreground space-y-0.5">
                <div>frame #{lastFrame.frame_index} · latency {lastFrame.latency_ms.toFixed(1)} ms</div>
                <div>img feature L2 {lastFrame.image_feature_l2.toFixed(2)}</div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

export default Inference
