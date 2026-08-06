/** Remote Compute Node settings page.

Lets the user list, add, edit, delete, and probe the configured RemoteCompute
nodes. The "local" node is always present and cannot be deleted.
*/
import { useCallback, useEffect, useState } from 'react'
import { Loader2, Plus, RefreshCw, Server, Trash2 } from 'lucide-react'
import { Button } from '../components/ui/button'
import {
  createRemoteComputeNode,
  deleteRemoteComputeNode,
  listRemoteComputeNodes,
  probeRemoteComputeNode,
  remoteComputeAcceleratorLabel,
  remoteComputeKindLabel,
  remoteComputeNodeSummary,
  setDefaultRemoteComputeNode,
  updateRemoteComputeNode,
  type RemoteComputeNode,
  type RemoteComputeKind,
  type RemoteComputeAccelerator,
} from '../lib/remoteComputeApi'

const EMPTY_DRAFT: Omit<RemoteComputeNode, 'created_at' | 'updated_at'> = {
  id: '',
  name: '',
  kind: 'remote_ssh',
  accelerator: 'cuda',
  sidecar_url: 'http://127.0.0.1:8010',
  ssh_host: '',
  ssh_user: '',
  ssh_port: 22,
  ssh_jump: '',
  model_root: '/home/user/outputs',
  default_model_path: '',
  policy_types: ['pi05'],
  enabled: true,
  description: '',
}

export function RemoteComputeSettings() {
  const [nodes, setNodes] = useState<RemoteComputeNode[]>([])
  const [defaultId, setDefaultId] = useState<string>('local')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [draft, setDraft] = useState<typeof EMPTY_DRAFT | null>(null)
  const [editId, setEditId] = useState<string | null>(null)
  const [probing, setProbing] = useState<Record<string, 'loading' | { ok: boolean; msg: string }>>({})

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const cfg = await listRemoteComputeNodes()
      setNodes(cfg.nodes || [])
      setDefaultId(cfg.default_node_id || 'local')
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const probe = useCallback(async (id: string) => {
    setProbing((p) => ({ ...p, [id]: 'loading' }))
    try {
      const r = await probeRemoteComputeNode(id)
      setProbing((p) => ({
        ...p,
        [id]: { ok: r.ok, msg: r.ok ? `已连接 · ${r.model_key || '无模型'}` : r.error || '无法连接' },
      }))
    } catch (e) {
      setProbing((p) => ({
        ...p,
        [id]: { ok: false, msg: e instanceof Error ? e.message : '探测失败' },
      }))
    }
  }, [])

  const onCreate = async () => {
    if (!draft || !draft.id || !draft.name) {
      setError('id 和 name 必填')
      return
    }
    try {
      await createRemoteComputeNode(draft)
      setDraft(null)
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : '创建失败')
    }
  }

  const onUpdate = async (id: string, patch: Partial<RemoteComputeNode>) => {
    try {
      await updateRemoteComputeNode(id, patch)
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : '更新失败')
    }
  }

  const onDelete = async (id: string) => {
    if (!window.confirm(`删除节点 ${id}？此操作不可撤销。`)) return
    try {
      await deleteRemoteComputeNode(id)
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : '删除失败')
    }
  }

  const onSetDefault = async (id: string) => {
    try {
      await setDefaultRemoteComputeNode(id)
      setDefaultId(id)
    } catch (e) {
      setError(e instanceof Error ? e.message : '设置默认失败')
    }
  }

  return (
    <div className="mx-auto max-w-4xl space-y-6 px-4 py-6">
      <header className="space-y-2">
        <h1 className="text-xl font-semibold">算力节点</h1>
        <p className="text-xs text-muted-foreground leading-relaxed">
          训练 / 推理走哪台机器，在这里选——这是真实业务流程，不是首页贴标。
          想用 <span className="text-[var(--ember)]">AMD · ROCm</span> 就选（或设为默认）本机 ROCm 节点；
          想用 <span className="text-sky-300">NVIDIA · CUDA</span> 就添加远端 GB10 / 云 GPU 并设为默认。
          两种可以并存，按任务切换。
        </p>
      </header>

      {error ? (
        <div className="rounded-md border border-red-500/40 bg-red-950/40 px-3 py-2 text-xs text-red-200">
          {error}
        </div>
      ) : null}

      {loading ? (
        <div className="flex items-center justify-center py-12 text-muted-foreground">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" /> 加载中…
        </div>
      ) : (
        <ul className="space-y-3">
          {nodes.map((n) => {
            const isDefault = n.id === defaultId
            const isLocal = n.id === 'local'
            const probeState = probing[n.id]
            return (
              <li
                key={n.id}
                className={`rounded-lg border px-4 py-3 ${
                  isDefault ? 'border-emerald-500/40 bg-emerald-950/10' : 'border-white/10 bg-black/20'
                }`}
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <Server className="h-3.5 w-3.5 shrink-0 text-sky-300" />
                      <span className="font-medium">{n.name}</span>
                      <span className="rounded bg-white/5 px-1.5 py-0.5 text-[10px] text-muted-foreground">
                        {remoteComputeKindLabel(n.kind)}
                      </span>
                      <span
                        className={`rounded px-1.5 py-0.5 text-[10px] ${
                          n.accelerator === 'rocm'
                            ? 'bg-[var(--ember)]/15 text-[var(--ember)]'
                            : n.accelerator === 'cuda'
                              ? 'bg-sky-500/15 text-sky-300'
                              : n.accelerator === 'cpu'
                                ? 'bg-white/10 text-slate-300'
                                : 'bg-white/5 text-muted-foreground'
                        }`}
                      >
                        {remoteComputeAcceleratorLabel(n.accelerator)}
                      </span>
                      {isDefault ? (
                        <span className="rounded bg-emerald-500/20 px-1.5 py-0.5 text-[10px] text-emerald-200">
                          默认 · 训练/推理走这里
                        </span>
                      ) : null}
                      {n.enabled ? null : (
                        <span className="rounded bg-amber-500/20 px-1.5 py-0.5 text-[10px] text-amber-200">
                          已禁用
                        </span>
                      )}
                    </div>
                    <p className="mt-1 break-all text-[11px] text-muted-foreground">
                      {remoteComputeNodeSummary(n)}
                    </p>
                    {n.description ? (
                      <p className="mt-1 text-[11px] text-muted-foreground">{n.description}</p>
                    ) : null}
                    {probeState ? (
                      <p
                        className={`mt-1 text-[11px] ${
                          probeState === 'loading'
                            ? 'text-sky-300'
                            : probeState.ok
                              ? 'text-emerald-300'
                              : 'text-amber-300'
                        }`}
                      >
                        {probeState === 'loading' ? '探测中…' : probeState.msg}
                      </p>
                    ) : null}
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={probeState === 'loading'}
                      onClick={() => void probe(n.id)}
                    >
                      {probeState === 'loading' ? (
                        <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                      ) : (
                        <RefreshCw className="mr-1 h-3 w-3" />
                      )}
                      探测
                    </Button>
                    {!isDefault ? (
                      <Button size="sm" variant="outline" onClick={() => void onSetDefault(n.id)}>
                        设为默认
                      </Button>
                    ) : null}
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => {
                        setEditId(n.id)
                        setDraft({ ...n })
                      }}
                    >
                      编辑
                    </Button>
                    {!isLocal ? (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => void onDelete(n.id)}
                        className="text-red-300"
                      >
                        <Trash2 className="mr-1 h-3 w-3" />
                        删除
                      </Button>
                    ) : null}
                  </div>
                </div>
              </li>
            )
          })}
        </ul>
      )}

      {draft ? (
        <NodeEditor
          draft={draft}
          editing={editId}
          onChange={setDraft}
          onCancel={() => {
            setDraft(null)
            setEditId(null)
          }}
          onSave={async () => {
            if (editId) {
              await onUpdate(editId, draft)
              setEditId(null)
              setDraft(null)
            } else {
              await onCreate()
            }
          }}
        />
      ) : (
        <Button variant="outline" onClick={() => setDraft({ ...EMPTY_DRAFT })}>
          <Plus className="mr-1 h-4 w-4" />
          添加节点
        </Button>
      )}
    </div>
  )
}

function NodeEditor({
  draft,
  editing,
  onChange,
  onCancel,
  onSave,
}: {
  draft: Omit<RemoteComputeNode, 'created_at' | 'updated_at'>
  editing: string | null
  onChange: (d: typeof EMPTY_DRAFT) => void
  onCancel: () => void
  onSave: () => void
}) {
  const isLocal = editing === 'local' || (!editing && draft.id === 'local')
  return (
    <div className="rounded-lg border border-sky-500/30 bg-sky-950/10 px-4 py-4 space-y-3">
      <h2 className="text-sm font-semibold">{editing ? `编辑节点 ${editing}` : '添加节点'}</h2>
      <div className="grid grid-cols-2 gap-3 text-xs">
        <Field label="ID（唯一标识）" disabled={!!editing}>
          <input
            className="w-full rounded-md border border-white/10 bg-black/30 px-2 py-1.5"
            value={draft.id}
            disabled={!!editing}
            onChange={(e) => onChange({ ...draft, id: e.target.value })}
            placeholder="my_gpu_box"
          />
        </Field>
        <Field label="名称">
          <input
            className="w-full rounded-md border border-white/10 bg-black/30 px-2 py-1.5"
            value={draft.name}
            onChange={(e) => onChange({ ...draft, name: e.target.value })}
            placeholder="我的 GPU 服务器"
          />
        </Field>
        <Field label="类型">
          <select
            className="w-full rounded-md border border-white/10 bg-black/30 px-2 py-1.5"
            value={draft.kind}
            disabled={isLocal}
            onChange={(e) => onChange({ ...draft, kind: e.target.value as RemoteComputeKind })}
          >
            <option value="local">本机（CPU/本地 GPU）</option>
            <option value="remote_ssh">远端（SSH + rsync）</option>
            <option value="remote_http">远端（仅 HTTP）</option>
          </select>
        </Field>
        <Field label="加速栈（训练/推理用什么）">
          <select
            className="w-full rounded-md border border-white/10 bg-black/30 px-2 py-1.5"
            value={draft.accelerator || 'auto'}
            onChange={(e) =>
              onChange({ ...draft, accelerator: e.target.value as RemoteComputeAccelerator })
            }
          >
            <option value="rocm">AMD · ROCm（本机 Radeon 推荐）</option>
            <option value="cuda">NVIDIA · CUDA（GB10 / 云 GPU）</option>
            <option value="cpu">CPU only</option>
            <option value="auto">自动探测</option>
          </select>
        </Field>
        <Field label="Sidecar URL">
          <input
            className="w-full rounded-md border border-white/10 bg-black/30 px-2 py-1.5"
            value={draft.sidecar_url}
            onChange={(e) => onChange({ ...draft, sidecar_url: e.target.value })}
            placeholder="http://192.168.1.10:8010"
          />
        </Field>
        {draft.kind !== 'local' ? (
          <>
            <Field label="SSH 主机">
              <input
                className="w-full rounded-md border border-white/10 bg-black/30 px-2 py-1.5"
                value={draft.ssh_host || ''}
                onChange={(e) => onChange({ ...draft, ssh_host: e.target.value })}
                placeholder="dgx-spark 或 192.168.1.10"
              />
            </Field>
            <Field label="SSH 用户">
              <input
                className="w-full rounded-md border border-white/10 bg-black/30 px-2 py-1.5"
                value={draft.ssh_user || ''}
                onChange={(e) => onChange({ ...draft, ssh_user: e.target.value })}
                placeholder="user"
              />
            </Field>
            <Field label="SSH 端口">
              <input
                type="number"
                className="w-full rounded-md border border-white/10 bg-black/30 px-2 py-1.5"
                value={draft.ssh_port ?? 22}
                onChange={(e) => onChange({ ...draft, ssh_port: Number(e.target.value) || 22 })}
              />
            </Field>
            <Field label="SSH ProxyJump（可选）">
              <input
                className="w-full rounded-md border border-white/10 bg-black/30 px-2 py-1.5"
                value={draft.ssh_jump || ''}
                onChange={(e) => onChange({ ...draft, ssh_jump: e.target.value })}
                placeholder="root@43.156.102.67"
              />
            </Field>
          </>
        ) : null}
        <Field label="模型根目录（远端或本机）">
          <input
            className="w-full rounded-md border border-white/10 bg-black/30 px-2 py-1.5"
            value={draft.model_root}
            onChange={(e) => onChange({ ...draft, model_root: e.target.value })}
            placeholder="/home/user/outputs"
          />
        </Field>
        <Field label="默认模型路径（可选）">
          <input
            className="w-full rounded-md border border-white/10 bg-black/30 px-2 py-1.5"
            value={draft.default_model_path || ''}
            onChange={(e) => onChange({ ...draft, default_model_path: e.target.value })}
            placeholder="/home/user/outputs/pi05_smoke_patched"
          />
        </Field>
        <Field label="描述（可选）">
          <input
            className="w-full rounded-md border border-white/10 bg-black/30 px-2 py-1.5"
            value={draft.description || ''}
            onChange={(e) => onChange({ ...draft, description: e.target.value })}
            placeholder="朋友的 GB10 / 家里的服务器 / 云 VM"
          />
        </Field>
        <Field label="启用">
          <input
            type="checkbox"
            checked={draft.enabled}
            disabled={isLocal}
            onChange={(e) => onChange({ ...draft, enabled: e.target.checked })}
          />
        </Field>
      </div>
      <div className="flex justify-end gap-2">
        <Button size="sm" variant="outline" onClick={onCancel}>
          取消
        </Button>
        <Button size="sm" onClick={onSave}>
          保存
        </Button>
      </div>
    </div>
  )
}

function Field({
  label,
  children,
  disabled,
}: {
  label: string
  children: React.ReactNode
  disabled?: boolean
}) {
  return (
    <label className={`block space-y-1 ${disabled ? 'opacity-50' : ''}`}>
      <span className="font-medium text-[11px] text-muted-foreground">{label}</span>
      {children}
    </label>
  )
}
