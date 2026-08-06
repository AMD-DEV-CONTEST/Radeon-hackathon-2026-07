import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { FormField, NumberIn } from './shared'
import {
  listRemoteComputeNodes,
  remoteComputeAcceleratorLabel,
  setDefaultRemoteComputeNode,
  type RemoteComputeNode,
} from '../../lib/remoteComputeApi'

const EPOCH_PRESETS = [5, 10, 20, 50]

export function LocalTrainingOptions({
  epochs,
  setEpochs,
}: {
  epochs: number
  setEpochs: (n: number) => void
}) {
  const [nodes, setNodes] = useState<RemoteComputeNode[]>([])
  const [defaultId, setDefaultId] = useState('local')
  const [loading, setLoading] = useState(true)
  const [switching, setSwitching] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [probing, setProbing] = useState(false)
  const [deviceProbe, setDeviceProbe] = useState<{
    ok: boolean | null
    accelerator: string
    device_name: string | null
    message: string
  } | null>(null)

  /** 本机计算设备探测（M48）：子进程隔离，走 realtime /api/remote_compute/device */
  const probeDevice = useCallback(async () => {
    setProbing(true)
    try {
      const res = await fetch('/api/remote_compute/device')
      if (!res.ok) throw new Error(`探测失败 (${res.status})`)
      setDeviceProbe((await res.json()) as typeof deviceProbe)
    } catch (e) {
      setDeviceProbe({ ok: null, accelerator: 'cpu', device_name: null, message: String(e) })
    } finally {
      setProbing(false)
    }
  }, [])

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const cfg = await listRemoteComputeNodes()
      setNodes((cfg.nodes || []).filter((n) => n.enabled))
      setDefaultId(cfg.default_node_id || 'local')
    } catch (e) {
      setError(e instanceof Error ? e.message : '无法加载算力节点（需 Local Agent）')
      setNodes([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const onPick = async (id: string) => {
    if (id === defaultId || switching) return
    setSwitching(true)
    setError(null)
    try {
      await setDefaultRemoteComputeNode(id)
      setDefaultId(id)
    } catch (e) {
      setError(e instanceof Error ? e.message : '切换失败')
    } finally {
      setSwitching(false)
    }
  }

  const selected = nodes.find((n) => n.id === defaultId)

  return (
    <div className="rounded-lg border border-emerald-500/25 bg-emerald-500/5 p-4 space-y-4">
      <div className="space-y-2">
        <p className="text-sm font-medium text-emerald-100">跑在哪台机器？</p>
        <p className="text-[11px] text-muted-foreground leading-relaxed">
          想用 AMD · ROCm 就选本机；想用 NVIDIA · CUDA 就选远端 GB10 / 云 GPU。
          这里设的是默认算力节点，训练后的部署也会走同一选择。
        </p>
        {loading ? (
          <p className="text-xs text-muted-foreground">加载算力节点…</p>
        ) : nodes.length === 0 ? (
          <p className="text-xs text-amber-200">
            暂无节点。请先在{' '}
            <Link to="/settings/remote-compute" className="underline text-[var(--ember)]">
              设置 → 算力节点
            </Link>{' '}
            配置。
          </p>
        ) : (
          <div className="grid gap-2">
            {nodes.map((n) => {
              const active = n.id === defaultId
              const acc = n.accelerator || 'auto'
              return (
                <button
                  key={n.id}
                  type="button"
                  disabled={switching}
                  onClick={() => void onPick(n.id)}
                  className={`w-full text-left rounded-md border px-3 py-2.5 transition-colors ${
                    active
                      ? acc === 'rocm'
                        ? 'border-[var(--ember)]/60 bg-[var(--ember)]/10'
                        : acc === 'cuda'
                          ? 'border-sky-400/50 bg-sky-500/10'
                          : 'border-primary bg-primary/10'
                      : 'border-border hover:bg-muted/40'
                  }`}
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-medium">{n.name}</span>
                    <span
                      className={`rounded px-1.5 py-0.5 text-[10px] ${
                        acc === 'rocm'
                          ? 'bg-[var(--ember)]/20 text-[var(--ember)]'
                          : acc === 'cuda'
                            ? 'bg-sky-500/20 text-sky-300'
                            : 'bg-white/10 text-muted-foreground'
                      }`}
                    >
                      {remoteComputeAcceleratorLabel(acc)}
                    </span>
                    {active ? (
                      <span className="rounded bg-emerald-500/20 px-1.5 py-0.5 text-[10px] text-emerald-200">
                        当前
                      </span>
                    ) : null}
                  </div>
                  {n.description ? (
                    <p className="mt-1 text-[10px] text-muted-foreground line-clamp-2">{n.description}</p>
                  ) : null}
                </button>
              )
            })}
          </div>
        )}
        {selected ? (
          <p className="text-[10px] text-muted-foreground">
            当前：{remoteComputeAcceleratorLabel(selected.accelerator)} · {selected.name}
            {' · '}
            <Link to="/settings/remote-compute" className="underline hover:text-foreground">
              管理节点
            </Link>
          </p>
        ) : null}
        {error ? <p className="text-[11px] text-amber-200">{error}</p> : null}

        {/* 本机计算探测（M48）：选节点前先看本机到底有没有可用 GPU */}
        <div className="flex items-center gap-2 pt-1">
          <button
            type="button"
            onClick={() => void probeDevice()}
            disabled={probing}
            className="rounded border border-border px-2 py-1 text-[10px] text-muted-foreground transition-colors hover:border-[var(--ember)]/40 hover:text-[var(--ember)] disabled:opacity-40"
          >
            {probing ? '探测中…' : '探测本机 GPU'}
          </button>
          {deviceProbe && (
            <span
              className={`text-[10px] ${deviceProbe.ok ? 'text-emerald-300' : 'text-stone-500'}`}
              title={deviceProbe.message}
            >
              {deviceProbe.ok
                ? `本机 ${deviceProbe.accelerator === 'rocm' ? 'AMD · ROCm' : deviceProbe.accelerator === 'cuda' ? 'NVIDIA · CUDA' : 'CPU'} ✓ ${deviceProbe.device_name ?? ''}`
                : '本机无可用 GPU（CPU only）'}
            </span>
          )}
        </div>
      </div>

      <p className="text-sm font-medium text-emerald-100">训练轮数</p>
      <FormField label="训练轮数（epoch）">
        <div className="flex flex-wrap gap-2 mb-2">
          {EPOCH_PRESETS.map((n) => (
            <button
              key={n}
              type="button"
              onClick={() => setEpochs(n)}
              className={`px-3 py-1.5 rounded-md border text-sm transition-colors ${
                epochs === n
                  ? 'border-primary bg-primary/15 text-primary'
                  : 'border-border hover:bg-muted/50'
              }`}
            >
              {n}
            </button>
          ))}
        </div>
        <NumberIn value={epochs} onChange={setEpochs} min={1} max={500} />
      </FormField>
    </div>
  )
}
