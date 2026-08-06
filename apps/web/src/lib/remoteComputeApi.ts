/** Remote Compute Node client.

A "Remote Compute Node" is any HTTP sidecar endpoint + optional SSH target
used to rsync model files there. It abstracts over:
  - local: sidecar runs on this laptop (CPU or local GPU)
  - remote_ssh: sidecar on a remote box reachable via SSH (e.g. a friend's GB10,
    a home server, a cloud VM)
  - remote_http: sidecar reachable via HTTP only (cloud inference endpoint)

Configuration is stored in ~/.cache/botversex/remote_compute.json on the
Local Agent side and managed via /api/remote_compute/* endpoints.
*/
import { agentFetch } from './localAgent'

export type RemoteComputeKind = 'local' | 'remote_ssh' | 'remote_http'

/** Which GPU vendor stack this node is meant to use for train/infer. */
export type RemoteComputeAccelerator = 'auto' | 'rocm' | 'cuda' | 'cpu'

export interface RemoteComputeNode {
  id: string
  name: string
  kind: RemoteComputeKind
  accelerator?: RemoteComputeAccelerator
  sidecar_url: string
  ssh_host?: string | null
  ssh_user?: string | null
  ssh_port?: number
  ssh_jump?: string | null
  model_root: string
  default_model_path?: string | null
  policy_types?: string[]
  enabled: boolean
  description?: string
  created_at?: number
  updated_at?: number
}

export interface RemoteComputeConfig {
  nodes: RemoteComputeNode[]
  default_node_id: string
}

export interface RemoteComputeProbeResult {
  ok: boolean
  sidecar_url?: string
  loaded?: boolean
  model_key?: string | null
  device?: string | null
  error?: string
  [key: string]: unknown
}

async function rcJson<T>(path: string, init?: RequestInit & { timeoutMs?: number }): Promise<T> {
  const timeoutMs = init?.timeoutMs ?? 30_000
  const { timeoutMs: _t, ...rest } = init ?? {}
  const res = await agentFetch(path, {
    ...rest,
    timeoutMs,
    headers: { 'Content-Type': 'application/json', ...rest.headers },
  })
  const text = await res.text().catch(() => '')
  if (!res.ok) {
    let detail = text || `Remote Compute API ${res.status}`
    try {
      const j = JSON.parse(text) as { detail?: string }
      if (j.detail) detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)
    } catch {
      /* keep raw */
    }
    throw new Error(detail)
  }
  return (text ? JSON.parse(text) : {}) as T
}

export function listRemoteComputeNodes() {
  return rcJson<RemoteComputeConfig>('/api/remote_compute/nodes')
}

export function createRemoteComputeNode(input: Omit<RemoteComputeNode, 'created_at' | 'updated_at'>) {
  return rcJson<{ ok: boolean; node: RemoteComputeNode }>('/api/remote_compute/nodes', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function updateRemoteComputeNode(id: string, patch: Partial<RemoteComputeNode>) {
  return rcJson<{ ok: boolean; node: RemoteComputeNode }>(`/api/remote_compute/nodes/${encodeURIComponent(id)}`, {
    method: 'PUT',
    body: JSON.stringify(patch),
  })
}

export function deleteRemoteComputeNode(id: string) {
  return rcJson<{ ok: boolean; deleted: number }>(`/api/remote_compute/nodes/${encodeURIComponent(id)}`, {
    method: 'DELETE',
  })
}

export function setDefaultRemoteComputeNode(nodeId: string) {
  return rcJson<{ ok: boolean; default_node_id: string }>('/api/remote_compute/default', {
    method: 'POST',
    body: JSON.stringify({ node_id: nodeId }),
  })
}

export function probeRemoteComputeNode(id: string) {
  return rcJson<RemoteComputeProbeResult>(`/api/remote_compute/nodes/${encodeURIComponent(id)}/probe`, {
    timeoutMs: 8_000,
  })
}

/** Convenience: human label for a node kind. */
export function remoteComputeKindLabel(kind: RemoteComputeKind): string {
  if (kind === 'local') return '本机'
  if (kind === 'remote_ssh') return '远端（SSH）'
  return '远端（HTTP）'
}

/** Human label for accelerator / vendor stack. */
export function remoteComputeAcceleratorLabel(acc?: RemoteComputeAccelerator | null): string {
  if (acc === 'rocm') return 'AMD · ROCm'
  if (acc === 'cuda') return 'NVIDIA · CUDA'
  if (acc === 'cpu') return 'CPU'
  return '自动探测'
}

/** Convenience: short summary line for a node. */
export function remoteComputeNodeSummary(n: RemoteComputeNode): string {
  const acc = remoteComputeAcceleratorLabel(n.accelerator)
  if (n.kind === 'local') return `${acc} · ${n.sidecar_url} · 本地模型目录 ${n.model_root}`
  if (n.kind === 'remote_ssh') {
    const target = n.ssh_user ? `${n.ssh_user}@${n.ssh_host}` : n.ssh_host
    return `${acc} · ${n.sidecar_url} · SSH ${target}${n.ssh_jump ? ` (经 ${n.ssh_jump})` : ''} · 远端目录 ${n.model_root}`
  }
  return `${acc} · ${n.sidecar_url} · 仅 HTTP`
}
