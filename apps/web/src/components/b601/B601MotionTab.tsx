import { useCallback, useEffect, useMemo, useState } from 'react'
import { Loader2, Rocket, Square } from 'lucide-react'
import { Button } from '../ui/button'
import type { TrainingJobDTO } from '../../types/training'
import {
  b601ModelKind,
  b601SidecarLoadModel,
  b601SidecarStatus,
  b601SyncModelToRemote,
  type B601CameraPrefs,
  type B601SidecarStatus,
} from '../../lib/b601Api'
import {
  listRemoteComputeNodes,
  remoteComputeAcceleratorLabel,
  remoteComputeKindLabel,
  remoteComputeNodeSummary,
  setDefaultRemoteComputeNode,
  type RemoteComputeNode,
} from '../../lib/remoteComputeApi'

interface Props {
  policyPath: string
  onPolicyPathChange: (v: string) => void
  onDeploy: (cameraIndices: number[]) => void
  onStopInference: () => void
  onGoVision?: () => void
  deploying: boolean
  inferenceRunning: boolean
  deployError?: string | null
  recentJobs: TrainingJobDTO[]
  cameraPrefs: B601CameraPrefs
}

type ModelOption = { value: string; label: string; group: string }

function shortTail(path: string, n = 36) {
  const s = path.trim()
  if (s.length <= n) return s
  return `…${s.slice(-(n - 1))}`
}

function buildOptions(
  jobs: TrainingJobDTO[],
  sidecar: B601SidecarStatus | null,
  currentPath: string,
): ModelOption[] {
  const out: ModelOption[] = []
  const seen = new Set<string>()
  const push = (value: string, label: string, group: string) => {
    const v = value.trim()
    if (!v || seen.has(v)) return
    seen.add(v)
    out.push({ value: v, label, group })
  }

  const loaded = typeof sidecar?.model_key === 'string' ? sidecar.model_key : ''
  if (sidecar?.ok && sidecar.loaded && loaded) {
    push(loaded, `当前算力节点已加载 · ${shortTail(loaded)}`, '就绪')
  }

  for (const j of jobs) {
    if (j.status !== 'succeeded') continue
    const mid = (j.model_id || (j.hparams?.output_model_id as string | undefined) || '').trim()
    if (!mid) continue
    const kind = b601ModelKind(`${j.dataset_id || ''} ${mid}`)
    const tag = kind === 'smoke' ? '试跑' : kind === 'full' ? '正式' : '完成'
    push(mid, `${tag} · ${j.dataset_id || j.id}`, '训练完成')
  }

  if (currentPath.trim()) {
    push(currentPath.trim(), `已选 · ${shortTail(currentPath)}`, '当前')
  }

  return out
}

export function B601MotionTab({
  policyPath,
  onPolicyPathChange,
  onDeploy,
  onStopInference,
  onGoVision,
  deploying,
  inferenceRunning,
  deployError,
  recentJobs,
  cameraPrefs,
}: Props) {
  const [sidecar, setSidecar] = useState<B601SidecarStatus | null>(null)
  const [busy, setBusy] = useState(false)
  const [hint, setHint] = useState<string | null>(null)
  const [nodes, setNodes] = useState<RemoteComputeNode[]>([])
  const [nodeId, setNodeId] = useState<string>('local')

  // Load remote compute nodes once on mount; default to the configured default.
  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const cfg = await listRemoteComputeNodes()
        if (cancelled) return
        const enabled = (cfg.nodes || []).filter((n) => n.enabled)
        setNodes(enabled)
        const def = cfg.default_node_id && enabled.some((n) => n.id === cfg.default_node_id)
          ? cfg.default_node_id
          : enabled[0]?.id || 'local'
        setNodeId(def)
      } catch {
        /* non-fatal: fall back to 'local' which the backend always has */
        if (cancelled) return
        setNodes([
          {
            id: 'local',
            name: '本机',
            kind: 'local',
            sidecar_url: 'http://127.0.0.1:8010',
            model_root: '',
            enabled: true,
          },
        ])
        setNodeId('local')
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const onPickNode = useCallback(async (id: string) => {
    setNodeId(id)
    try {
      await setDefaultRemoteComputeNode(id)
    } catch {
      /* non-fatal */
    }
  }, [])

  const options = useMemo(
    () => buildOptions(recentJobs, sidecar, policyPath),
    [recentJobs, sidecar, policyPath],
  )

  const refreshSidecar = useCallback(async () => {
    try {
      setSidecar(await b601SidecarStatus(undefined, nodeId))
    } catch (e) {
      setSidecar({
        ok: false,
        loaded: false,
        error: e instanceof Error ? e.message : 'unreachable',
      })
    }
  }, [nodeId])

  useEffect(() => {
    void refreshSidecar()
    const t = window.setInterval(() => void refreshSidecar(), 15_000)
    return () => window.clearInterval(t)
  }, [refreshSidecar])

  // Auto-pick a model so users never have to type a path.
  useEffect(() => {
    if (policyPath.trim()) return
    if (options.length === 0) return
    onPolicyPathChange(options[0].value)
  }, [options, policyPath, onPolicyPathChange])

  const selectValue = useMemo(() => {
    const cur = policyPath.trim()
    if (cur && options.some((o) => o.value === cur)) return cur
    if (options[0]) return options[0].value
    return ''
  }, [policyPath, options])

  const onSelectChange = (value: string) => {
    onPolicyPathChange(value)
  }

  const ensureLoadedThenDeploy = async () => {
    const model = (policyPath || selectValue).trim()
    if (!model) {
      window.alert('还没有可选模型。请先完成训练，或确认算力节点已加载模型。')
      return
    }
    if (cameraPrefs.front === cameraPrefs.side) {
      window.alert('正面和侧面相机相同。请先到「视觉」里改好。')
      onGoVision?.()
      return
    }
    const ok = window.confirm(
      `部署到机械臂？\n\n模型：${shortTail(model, 60)}\n正面相机：Cam ${cameraPrefs.front}\n侧面相机：Cam ${cameraPrefs.side}\n\n周围留空；异常立刻急停。`,
    )
    if (!ok) return

    // If sidecar has another model, hot-load the selected one first.
    const loaded = typeof sidecar?.model_key === 'string' ? sidecar.model_key : ''
    if (sidecar?.ok && loaded !== model) {
      setBusy(true)
      setHint('正在把所选模型加载到算力节点…')
      try {
        await b601SidecarLoadModel({ modelKey: model, nodeId })
        await refreshSidecar()
      } catch (e) {
        setHint(e instanceof Error ? e.message : '加载失败')
        setBusy(false)
        return
      }
      setBusy(false)
      setHint(null)
    }

    onPolicyPathChange(model)
    onDeploy([cameraPrefs.front, cameraPrefs.side])
  }

  const syncSelected = async () => {
    const model = (policyPath || selectValue).trim()
    if (!model) return
    const job = recentJobs.find(
      (j) => j.model_id === model || j.hparams?.output_model_id === model,
    )
    setBusy(true)
    setHint('正在同步到算力节点…')
    try {
      await b601SyncModelToRemote({
        modelId: model,
        jobId: (job?.hparams?.qualia_job_id as string | undefined) || undefined,
        nodeId: nodeId ?? undefined,
        load: true,
      })
      setHint('已开始同步，完成后可直接部署')
      window.setTimeout(() => setHint(null), 4000)
      void refreshSidecar()
    } catch (e) {
      setHint(e instanceof Error ? e.message : '同步失败')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      <p className="text-xs text-muted-foreground leading-relaxed">
        选一个训练好的模型，确认相机后一键部署。不用手填路径。部署前会自动关掉「视觉」预览，避免相机被占用。
      </p>

      <div className="space-y-2">
        <label className="block space-y-1 text-xs">
          <span className="font-medium">算力节点</span>
          <select
            className="w-full rounded-md border border-white/10 bg-black/30 px-2 py-2 text-sm"
            value={nodeId}
            disabled={inferenceRunning || nodes.length === 0}
            onChange={(e) => void onPickNode(e.target.value)}
          >
            {nodes.length === 0 ? (
              <option value="local">本机</option>
            ) : (
              nodes.map((n) => (
                <option key={n.id} value={n.id}>
                  [{remoteComputeAcceleratorLabel(n.accelerator)}] {n.name} · {remoteComputeKindLabel(n.kind)}
                </option>
              ))
            )}
          </select>
          <span className="block text-[10px] text-muted-foreground">
            {nodes.find((n) => n.id === nodeId)
              ? remoteComputeNodeSummary(nodes.find((n) => n.id === nodeId)!)
              : '在「设置 → 算力节点」选 AMD·ROCm（本机）或 NVIDIA·CUDA（远端）'}
          </span>
        </label>
      </div>

      <div className="space-y-2">
        <label className="block space-y-1 text-xs">
          <span className="font-medium">选择模型</span>
          <select
            className="w-full rounded-md border border-white/10 bg-black/30 px-2 py-2 text-sm"
            value={selectValue}
            disabled={inferenceRunning || options.length === 0}
            onChange={(e) => onSelectChange(e.target.value)}
          >
            {options.length === 0 ? (
              <option value="">暂无可用模型 — 请先去训练</option>
            ) : (
              options.map((o) => (
                <option key={o.value} value={o.value}>
                  [{o.group}] {o.label}
                </option>
              ))
            )}
          </select>
        </label>
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            variant="outline"
            disabled={busy || !selectValue || inferenceRunning}
            onClick={() => void syncSelected()}
          >
            {busy ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : null}
            同步到算力节点
          </Button>
        </div>
        {hint ? <p className="text-[11px] text-emerald-300">{hint}</p> : null}
        {sidecar && !sidecar.ok ? (
          <p className="text-[11px] text-amber-200">算力节点未连接，部署前请确认远程推理服务已启动。</p>
        ) : null}
      </div>

      <div className="rounded-md border border-white/10 bg-black/20 px-3 py-2 text-xs">
        <p className="font-medium">相机（来自「视觉」）</p>
        <p className="mt-1 text-muted-foreground">
          正面 Cam {cameraPrefs.front} · 侧面 Cam {cameraPrefs.side}
          {cameraPrefs.top != null ? ` · 顶部 Cam ${cameraPrefs.top}` : ''}
        </p>
        {onGoVision ? (
          <button
            type="button"
            className="mt-2 text-[11px] text-sky-300 hover:underline"
            onClick={onGoVision}
          >
            去视觉里改相机 / 预览
          </button>
        ) : null}
      </div>

      {inferenceRunning ? (
        <Button
          size="lg"
          variant="destructive"
          className="h-12 w-full text-base font-bold border-2 border-red-400"
          onClick={onStopInference}
          disabled={deploying}
        >
          {deploying ? <Loader2 className="mr-1.5 h-5 w-5 animate-spin" /> : <Square className="mr-1.5 h-5 w-5 fill-current" />}
          急停
        </Button>
      ) : (
        <div className="space-y-2">
          <Button
            size="sm"
            className="w-full"
            disabled={deploying || busy || options.length === 0}
            onClick={() => void ensureLoadedThenDeploy()}
          >
            {deploying || busy ? (
              <Loader2 className="mr-1 h-4 w-4 animate-spin" />
            ) : (
              <Rocket className="mr-1 h-4 w-4" />
            )}
            {deploying || busy ? '准备中…' : '部署到机械臂'}
          </Button>
          {deployError ? (
            <p className="rounded border border-red-500/40 bg-red-500/10 px-2 py-1.5 text-[11px] text-red-300">
              {deployError}
            </p>
          ) : null}
        </div>
      )}
    </div>
  )
}
