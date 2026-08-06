// XAI 后端 API 层：token 自动获取 + SSE 对话流
// 后端契约（运行实例实测，2026-07-23）：
//   GET  /api/auth/token   → 免鉴权，返回 { token }
//   GET  /api/status       → 需 X-Auth-Token
//   POST /api/chat         → SSE 流式对话，body { text, session, kernel }
//   SSE 事件: start / intent / guard / plan / progress / token / answer / done / [DONE]

let _token: string | null = null

// 后端地址：默认同源（空串 → 相对路径）。设置弹窗写入 localStorage['xai_backend_url'] 后生效，
// 用于远程/多后端部署场景；本地单机默认留空即可。
export function apiBase(): string {
  try {
    const u = localStorage.getItem("xai_backend_url")
    return u ? u.replace(/\/+$/, "") : ""
  } catch {
    return ""
  }
}

export async function getToken(force = false): Promise<string> {
  if (_token && !force) return _token
  const res = await fetch(apiBase() + "/api/auth/token")
  if (!res.ok) throw new Error("获取 token 失败: HTTP " + res.status)
  const data = await res.json()
  _token = data.token || ""
  return _token
}

async function authed(method: string, path: string): Promise<Response> {
  const token = await getToken()
  return fetch(apiBase() + path, {
    method,
    headers: { "Content-Type": "application/json", "X-Auth-Token": token },
  })
}

export interface SystemStatus {
  xai_engine?: string
  model?: string
  pending_approvals?: number
  [k: string]: any
}

export async function fetchStatus(): Promise<SystemStatus> {
  const res = await authed("GET", "/api/status")
  if (!res.ok) throw new Error("status " + res.status)
  return res.json()
}

// ── 系统面（B1/B2/B3/B5 落地，运行实例实测 2026-07-24）──────────
// GET /api/system/health  → { healthy, ts, xai_engine, model, project, ... }（豁免鉴权）
// GET /api/system/sandbox → { os, available_backends, policy, effective }
// GET /api/system/errors  → { count, tracked_since, errors[] }

export interface SystemHealth {
  healthy: boolean;
  ts: number;
  xai_engine?: string;
  [k: string]: any;
}
export async function fetchSystemHealth(): Promise<SystemHealth> {
  const res = await authed("GET", "/api/system/health")
  if (!res.ok) throw new Error("system health " + res.status)
  return res.json()
}

export interface SystemSandbox {
  os: string;
  available_backends: string[];
  policy: string;
  effective: string;
}
export async function fetchSystemSandbox(): Promise<SystemSandbox> {
  const res = await authed("GET", "/api/system/sandbox")
  if (!res.ok) throw new Error("system sandbox " + res.status)
  return res.json()
}

export interface SystemErrors {
  count: number;
  tracked_since: number;
  errors: any[];
}
export async function fetchSystemErrors(): Promise<SystemErrors> {
  const res = await authed("GET", "/api/system/errors")
  if (!res.ok) throw new Error("system errors " + res.status)
  return res.json()
}

// ── 会话历史（运行实例实测 2026-07-23）────────────────────
// GET    /api/sessions                → { sessions: SessionMeta[] }（72 个真实会话）
// GET    /api/sessions/<id>/messages  → { session, messages: [{role, content}] }（limit=500）
// DELETE /api/sessions/<id>           → 204

export interface SessionMeta {
  id: string
  session: string
  title: string
  last_role: string
  last_content: string
  last_active_at: string
  created_at: string
  message_count: number
  ts: number
}

export interface SessionMessage {
  role: string
  content: string
}

export async function listSessions(): Promise<SessionMeta[]> {
  const res = await authed("GET", "/api/sessions")
  if (!res.ok) throw new Error("sessions " + res.status)
  const data = await res.json()
  return data.sessions || []
}

export async function getSessionMessages(id: string): Promise<SessionMessage[]> {
  const res = await authed("GET", "/api/sessions/" + encodeURIComponent(id) + "/messages")
  if (!res.ok) throw new Error("messages " + res.status)
  const data = await res.json()
  return data.messages || []
}

export async function deleteSession(id: string): Promise<void> {
  const res = await authed("DELETE", "/api/sessions/" + encodeURIComponent(id))
  if (!res.ok && res.status !== 204) throw new Error("delete " + res.status)
}

// ── 节点⑤ 七页数据接线（运行实例实测 2026-07-23）──────────
// /api/agents          → { agents:[{name,role,backend,id}], rooms:[] }
// /api/memory/stats    → { layers:{working|short_term|...:{count,hit_rate,health,capacity}}, summary, trends, heatmap, funnel, scatter }
// /api/memory/list     → { entries:[{id,layer,engine,key,value,importance,meta,created_at,accessed_at}] }（layer 参数后端忽略，前端自行过滤）
// /api/guardian/pending→ { pending:[] }
// POST /api/guardian/approve → body {ticket_id, human_ok, reason}
// /api/gepa/status     → { running,last_run,last_trigger,generation,pareto_frontier_size,interval_hours,last_error }
// /api/workflow/history→ { history:[] }
// ⚠️ /api/dashboard 运行实例报 "_EVENT_LOCK is not defined"（源码正常，进程漂移），前端绕开不用

export interface AgentInfo {
  name: string
  role: string
  backend: string
  id: string
}

export async function fetchAgents(): Promise<AgentInfo[]> {
  const res = await authed("GET", "/api/agents")
  if (!res.ok) throw new Error("agents " + res.status)
  const data = await res.json()
  return data.agents || []
}

export interface MemoryLayerStat {
  count: number
  hit_rate: number
  health: number
  capacity: number
}

export interface MemoryStats {
  layers: Record<string, MemoryLayerStat>
  summary?: any
  [k: string]: any
}

export async function fetchMemoryStats(): Promise<MemoryStats> {
  const res = await authed("GET", "/api/memory/stats")
  if (!res.ok) throw new Error("memory stats " + res.status)
  return res.json()
}

export interface GuardianTicket {
  ticket_id?: string
  id?: string
  action?: string
  risk?: string
  reason?: string
  suggestion?: string
  // 后端 pending_approvals 实际字段（create_approval → /api/guardian/pending）
  type?: string          // grok_write | delete_file | run_command | network | rm_rf | general
  detail?: string        // 动作详情（grok_write 为任务文本）
  intent?: string        // grok_build 等
  level?: number
  level_name?: string    // P0 | P1 | P2
  session?: string
  status?: string
  [k: string]: any
}

export async function fetchGuardianPending(): Promise<GuardianTicket[]> {
  const res = await authed("GET", "/api/guardian/pending")
  if (!res.ok) throw new Error("guardian " + res.status)
  const data = await res.json()
  return data.pending || []
}

export async function guardianApprove(ticketId: string, ok: boolean, reason = ""): Promise<any> {
  const token = await getToken()
  const res = await fetch(apiBase() + "/api/guardian/approve", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({ ticket_id: ticketId, human_ok: ok, reason }),
  })
  if (!res.ok) {
    let msg = "HTTP " + res.status
    try { msg = (await res.json()).error || msg } catch {}
    throw new Error(msg)
  }
  return res.json()
}

// ---- 备忘录日历 (Memo Calendar) ----
export interface Memo {
  id: string
  title: string
  notes?: string
  date: string            // YYYY-MM-DD
  time?: string          // HH:mm，空=全天
  allDay?: boolean
  rrule?: string         // RFC5545 重复规则，空=单次
  done?: boolean
  priority?: "low" | "mid" | "high"
  color?: "logic" | "system" | "input" | "data" | "ai"
  created_at?: number
}

export async function fetchMemos(): Promise<Memo[]> {
  const res = await authed("GET", "/api/memos")
  if (!res.ok) throw new Error("memos " + res.status)
  const data = await res.json()
  return data.memos || []
}

export async function createMemo(memo: Partial<Memo>): Promise<Memo> {
  const r = await authedRaw("POST", "/api/memos", memo)
  if (!r.ok) throw new Error("create memo " + r.status)
  return (await r.json()).memo
}

export async function updateMemo(id: string, patch: Partial<Memo>): Promise<Memo> {
  const r = await authedRaw("POST", "/api/memos/update", { id, ...patch })
  if (!r.ok) throw new Error("update memo " + r.status)
  return (await r.json()).memo
}

export async function deleteMemo(id: string): Promise<void> {
  const r = await authedRaw("POST", "/api/memos/delete", { id })
  if (!r.ok) throw new Error("delete memo " + r.status)
}

export async function requestGrokWrite(task: string, reason = "Grok Build 写操作需人工审批"): Promise<{ ok: boolean; id: string; status: string }> {
  const token = await getToken()
  const res = await fetch(apiBase() + "/api/guardian/grok-write/request", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({ task, reason }),
  })
  if (!res.ok) {
    let msg = "HTTP " + res.status
    try { msg = (await res.json()).error || msg } catch {}
    throw new Error(msg)
  }
  return res.json()
}

// authed 但带 body 的底层封装（memos 用）
async function authedRaw(method: string, path: string, body: any): Promise<Response> {
  const token = await getToken()
  return fetch(path, {
    method,
    headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify(body || {}),
  })
}

// 语义记忆检索（mode=semantic 走向量余弦召回）
export async function fetchMemoryContextSemantic(text: string, limit = 10): Promise<any> {
  const token = await getToken()
  const res = await fetch(`${apiBase()}/api/memory/context?text=${encodeURIComponent(text)}&mode=semantic&limit=${limit}`, {
    headers: { "X-Auth-Token": token },
  })
  if (!res.ok) throw new Error("memory context " + res.status)
  return res.json()
}

export interface GepaStatus {
  running: boolean
  last_run: number
  last_trigger: string
  generation: number
  pareto_frontier_size: number
  interval_hours: number
  last_error: string
}

export async function fetchGepaStatus(): Promise<GepaStatus> {
  const res = await authed("GET", "/api/gepa/status")
  if (!res.ok) throw new Error("gepa " + res.status)
  return res.json()
}

export interface GatewayStatus {
  ok: boolean
  simulated: boolean
  simulated_capabilities: string[]
  capabilities: string[]
  note: string
}

export async function fetchGatewayStatus(): Promise<GatewayStatus> {
  const res = await authed("GET", "/api/gateway/status")
  if (!res.ok) throw new Error("gateway " + res.status)
  return res.json()
}

export async function fetchWorkflowHistory(): Promise<any[]> {
  const res = await authed("GET", "/api/workflow/history")
  if (!res.ok) throw new Error("workflow history " + res.status)
  const data = await res.json()
  return data.history || []
}

// ── 节点⑥ 能力注册表 + 工具中心（运行实例实测 2026-07-23）────
// /api/capabilities → { capabilities:[{id,name,type,status,description,meta}] }（type: agent|skill|tool）
// /api/skills       → { skills:[{name,trigger,body,source}] }
// /api/mcp/list     → { mcps:[{id,name,type,command,url,args,env,enabled}] }
// /api/connectors   → { connectors:[{name,type,command,args,url,env,status,last_active}] }

export interface Capability {
  id: string
  name: string
  type: string // agent | skill | tool
  status: string
  description: string
  meta: string
}

export async function fetchCapabilities(): Promise<Capability[]> {
  const res = await authed("GET", "/api/capabilities")
  if (!res.ok) throw new Error("capabilities " + res.status)
  const data = await res.json()
  return data.capabilities || []
}

export interface SkillDef {
  name: string
  trigger: string
  body: string
  source: string
}

export async function fetchSkills(): Promise<SkillDef[]> {
  const res = await authed("GET", "/api/skills")
  if (!res.ok) throw new Error("skills " + res.status)
  const data = await res.json()
  return data.skills || []
}

export interface McpEntry {
  id: number
  name: string
  type: string
  command: string
  url: string
  args: string[]
  env: Record<string, string>
  enabled: boolean
}

export async function fetchMcpList(): Promise<McpEntry[]> {
  const res = await authed("GET", "/api/mcp/list")
  if (!res.ok) throw new Error("mcp list " + res.status)
  const data = await res.json()
  return data.mcps || []
}

export interface ConnectorEntry {
  name: string
  type: string
  command: string
  args: string[]
  url: string
  env: Record<string, string>
  status: string
  last_active: string
}

export async function fetchConnectors(): Promise<ConnectorEntry[]> {
  const res = await authed("GET", "/api/connectors")
  if (!res.ok) throw new Error("connectors " + res.status)
  const data = await res.json()
  return data.connectors || []
}

// ── 节点⑦ 知识库（运行实例实测 2026-07-23）──────────────────
// GET  /api/knowledge/stats  → { ok, stats:{total_chunks,sources,dense_available,built}, error }（可用）
// POST /api/knowledge/search → { ok, hits:[], error }
//   ⚠️ 源码 533 行存在，但运行实例返回 404（旧代码漂移，重启后可用）→ 前端优雅降级

export interface KnowledgeStats {
  total_chunks: number
  sources: number
  dense_available: boolean
  built: boolean
}

export async function fetchKnowledgeStats(): Promise<KnowledgeStats> {
  const res = await authed("GET", "/api/knowledge/stats")
  if (!res.ok) throw new Error("knowledge stats " + res.status)
  const data = await res.json()
  if (!data.ok) throw new Error(data.error || "知识库不可用")
  return data.stats
}

export async function searchKnowledge(query: string, topK = 5): Promise<any[]> {
  const token = await getToken()
  const res = await fetch(apiBase() + "/api/knowledge/search", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({ query, top_k: topK }),
  })
  const data = await res.json().catch(() => ({}))
  if (res.status === 404 || data.path === "/api/knowledge/search") {
    throw new Error("SEARCH_NOT_DEPLOYED") // 运行实例为旧代码，重启后端后可用
  }
  if (!res.ok || data.ok === false) throw new Error(data.error || "搜索失败 " + res.status)
  return data.hits || []
}

/* ---------- 记忆搜索（@提及） ---------- */
export interface MemorySearchHit {
  layer: string
  key: string
  value: string
  score: number
}

// GET /api/memory/search?q=&limit= → { query, layer, results:[{layer,key,value,score}] }
export async function searchMemory(query: string, limit = 8): Promise<MemorySearchHit[]> {
  const token = await getToken()
  try {
    const res = await fetch(`${apiBase()}/api/memory/search?q=${encodeURIComponent(query)}&limit=${limit}`, {
      headers: { "X-Auth-Token": token },
    })
    if (!res.ok) return []
    const data = await res.json().catch(() => ({ results: [] }))
    return data.results || []
  } catch {
    return []
  }
}

// ── 记忆 CRUD（近期参考 5.3.3 "长期记忆展示与编辑"）────
// GET    /api/memory/list?layer=&keyword=&limit=50
// POST   /api/memory/store  {layer, key, value[, engine][, importance]}
// PUT    /api/memory/<id>   {value?, importance?}
// DELETE /api/memory/<id>   → {ok, deleted}

export interface MemoryEntry {
  id: number
  layer: string
  engine: string
  key: string
  value: string
  importance: number
  meta?: Record<string, any>
  created_at: number
  accessed_at: number
}

export async function fetchMemoryList(layer?: string, keyword?: string, limit = 50): Promise<MemoryEntry[]> {
  const params = new URLSearchParams()
  if (layer) params.set("layer", layer)
  if (keyword) params.set("keyword", keyword)
  params.set("limit", String(limit))
  const res = await authed("GET", `/api/memory/list?${params.toString()}`)
  if (!res.ok) throw new Error("memory list " + res.status)
  const data = await res.json()
  return data.entries || []
}

export async function storeMemory(layer: string, key: string, value: string, engine = "xai", importance = 0.5): Promise<number> {
  const token = await getToken()
  const res = await fetch(apiBase() + "/api/memory/store", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({ layer, key, value, engine, importance }),
  })
  if (!res.ok) throw new Error("memory store " + res.status)
  const data = await res.json()
  if (!data.ok) throw new Error(data.error || "存储失败")
  return data.id
}

export async function updateMemory(id: number, value?: string, importance?: number): Promise<void> {
  const token = await getToken()
    const res = await fetch(`${apiBase()}/api/memory/${id}`, {
      method: "PUT",
    headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({ value, importance }),
  })
  if (!res.ok) throw new Error("memory update " + res.status)
}

export async function deleteMemory(id: number): Promise<boolean> {
  const token = await getToken()
    const res = await fetch(`${apiBase()}/api/memory/${id}`, {
      method: "DELETE",
    headers: { "X-Auth-Token": token },
  })
  if (!res.ok) throw new Error("memory delete " + res.status)
  const data = await res.json()
  return data.deleted || false
}

// GET /api/canvas/<cid> → { id, nodes:[{id,type,position,data:{label}}], edges:[...] }
export interface CanvasNode {
  id: string
  type?: string
  position?: { x: number; y: number }
  data?: { label?: string; [k: string]: any }
  [k: string]: any
}
export interface CanvasData {
  id: string
  nodes: CanvasNode[]
  edges: Array<{ id?: string; source: string; target: string; [k: string]: any }>
  updated_at?: string
  version?: number
}
export async function fetchCanvas(cid = "main"): Promise<CanvasData> {
  const token = await getToken()
  try {
    const res = await fetch(`${apiBase()}/api/canvas/${encodeURIComponent(cid)}`, {
      headers: { "X-Auth-Token": token },
    })
    if (!res.ok) return { id: cid, nodes: [], edges: [] }
    return await res.json()
  } catch {
    return { id: cid, nodes: [], edges: [] }
  }
}

export interface ChatEvent {
  type: string
  [k: string]: any
}

export interface SendChatOpts {
  text: string
  kernel?: "" | "hermes" | "grok_build"
  session?: string
  onEvent: (ev: ChatEvent) => void
  signal?: AbortSignal
}

// POST /api/chat，读取 SSE 流，逐事件回调。流以 data: [DONE] 结束。
export async function sendChat(opts: SendChatOpts): Promise<void> {
  const token = await getToken()
  const res = await fetch(apiBase() + "/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({
      text: opts.text,
      session: opts.session || "default",
      kernel: opts.kernel || "",
    }),
    signal: opts.signal,
  })
  if (!res.ok) {
    let msg = "HTTP " + res.status
    try {
      const j = await res.json()
      msg = j.error || msg
    } catch {}
    throw new Error(msg)
  }
  if (!res.body) throw new Error("后端未返回响应流")

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ""
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    let idx: number
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const raw = buf.slice(0, idx)
      buf = buf.slice(idx + 2)
      const line = raw.split("\n").find((l) => l.startsWith("data:"))
      if (!line) continue
      const payload = line.slice(5).trim()
      if (payload === "[DONE]") {
        opts.onEvent({ type: "[DONE]" })
        return
      }
      try {
        opts.onEvent(JSON.parse(payload))
      } catch {
        /* 忽略无法解析的片段 */
      }
    }
  }
  opts.onEvent({ type: "[DONE]" })
}

// ── Grok Build 代码引擎（v0.2.111 完整嵌入，运行实例实测 2026-07-24）──────
// GET  /api/grok/health        → { grok_build_bridge, version, binary }
// GET  /api/grok/models        → { ok, models[], default, count }
// GET  /api/grok/capabilities  → { available, binary, capabilities[] }
// GET  /api/grok/inspect       → { ok, output } 当前目录配置发现
// POST /api/grok/run           → headless 真实执行，返回 { text, thought, usage, num_turns }

export interface GrokHealth {
  grok_build_bridge: string
  version?: string
  binary?: string
  reason?: string
}
export async function fetchGrokHealth(): Promise<GrokHealth> {
  const res = await authed("GET", "/api/grok/health")
  if (!res.ok) throw new Error("grok health " + res.status)
  return res.json()
}

export interface GrokModels {
  ok: boolean
  models: string[]
  default: string | null
  count?: number
}
export async function fetchGrokModels(): Promise<GrokModels> {
  const res = await authed("GET", "/api/grok/models")
  if (!res.ok) throw new Error("grok models " + res.status)
  return res.json()
}

export interface GrokCapability {
  id: string
  name: string
  flag: string
  desc: string
  wired: boolean
}
export interface GrokCapabilities {
  available: boolean
  binary?: string
  capabilities: GrokCapability[]
}
export async function fetchGrokCapabilities(): Promise<GrokCapabilities> {
  const res = await authed("GET", "/api/grok/capabilities")
  if (!res.ok) throw new Error("grok capabilities " + res.status)
  return res.json()
}

export async function fetchGrokInspect(): Promise<{ ok: boolean; output?: string; error?: string }> {
  const res = await authed("GET", "/api/grok/inspect")
  if (!res.ok) throw new Error("grok inspect " + res.status)
  return res.json()
}

export interface GrokRunOpts {
  task: string
  model?: string
  check?: boolean
  best_of_n?: number
  max_turns?: number
  disable_web?: boolean
  timeout?: number
}
export interface GrokRunResult {
  ok?: boolean
  text?: string
  thought?: string
  raw?: string
  error?: string
  num_turns?: number
  usage?: { total_tokens?: number; input_tokens?: number; output_tokens?: number }
  modelUsage?: Record<string, any>
  sessionId?: string
  truncated?: boolean
  partial_output?: string
}
export async function runGrok(opts: GrokRunOpts): Promise<GrokRunResult> {
  const token = await getToken()
  const res = await fetch(apiBase() + "/api/grok/run", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({
      task: opts.task,
      model: opts.model || "",
      check: !!opts.check,
      best_of_n: opts.best_of_n || 0,
      max_turns: opts.max_turns || 0,
      disable_web: opts.disable_web !== false,
      timeout: opts.timeout || 300,
    }),
  })
  if (!res.ok) {
    let msg = "HTTP " + res.status
    try { const j = await res.json(); msg = j.error || msg } catch {}
    throw new Error(msg)
  }
  return res.json()
}

// ── 意图预分类（前端路由提示用）────────────────────────
// POST /api/intent → { intent, confidence, kernel }  kernel: grok_build | hermes | openclaw
export async function classifyIntent(text: string): Promise<{ intent: string; confidence: number; kernel: string }> {
  const token = await getToken()
  try {
    const res = await fetch(apiBase() + "/api/intent", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Auth-Token": token },
      body: JSON.stringify({ text }),
    })
    if (!res.ok) return { intent: "chat", confidence: 0, kernel: "hermes" }
    const d = await res.json().catch(() => ({}))
    return { intent: d.intent || "chat", confidence: d.confidence || 0, kernel: d.kernel || "hermes" }
  } catch {
    return { intent: "chat", confidence: 0, kernel: "hermes" }
  }
}

// ── Grok 模型同步偏好 ───────────────────────────────────
// GET  /api/grok/model    → { ok, model, overidden }
// POST /api/grok/model/set → { ok, model }  （model 空串=清除，回到引擎推导）
export interface GrokModelPref {
  ok: boolean
  model: string
  overidden: boolean
  engine_derived?: string
}
export async function fetchGrokModel(): Promise<GrokModelPref> {
  const res = await authed("GET", "/api/grok/model")
  if (!res.ok) throw new Error("grok model " + res.status)
  return res.json()
}
export async function setGrokModel(model: string): Promise<{ ok: boolean; model: string }> {
  const token = await getToken()
  const res = await fetch(apiBase() + "/api/grok/model/set", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({ model: model || "" }),
  })
  if (!res.ok) throw new Error("grok model set " + res.status)
  return res.json()
}

// ── Grok 运行历史（XAI 自有，每次 run 后自动落盘）────────────
// GET  /api/grok/history         → { ok, count, runs: GrokHistoryItem[] }
// GET  /api/grok/history/<id>   → 完整记录（含 result_json，用于恢复）
// DELETE /api/grok/history/<id> → { ok, deleted, id }
export interface GrokHistoryItem {
  id: string
  ts: number
  task: string
  model: string | null
  ok: number
  summary: string
  grok_session_id?: string | null
}
export interface GrokHistoryRecord extends GrokHistoryItem {
  result_json: GrokRunResult
}
export async function fetchGrokHistory(limit = 100): Promise<{ ok: boolean; count: number; runs: GrokHistoryItem[] }> {
  const res = await authed("GET", "/api/grok/history?limit=" + limit)
  if (!res.ok) throw new Error("grok history " + res.status)
  return res.json()
}
export async function fetchGrokHistoryItem(id: string): Promise<GrokHistoryRecord> {
  const res = await authed("GET", "/api/grok/history/" + encodeURIComponent(id))
  if (!res.ok) throw new Error("grok history item " + res.status)
  return res.json()
}
export async function deleteGrokHistory(id: string): Promise<{ ok: boolean; deleted: boolean; id: string }> {
  const token = await getToken()
  const res = await fetch(apiBase() + "/api/grok/history/" + encodeURIComponent(id), {
    method: "DELETE",
    headers: { "X-Auth-Token": token },
  })
  if (!res.ok) throw new Error("grok history delete " + res.status)
  return res.json()
}

// ── 模型管理 ──────────────────────────────────────────────

export interface ModelEntry {
  id: string
  name: string
  provider: string
  model: string
  base_url: string
  api_key: string
  is_active: boolean
  vision?: boolean
  created_at: number
}

export interface ModelListResponse {
  models: ModelEntry[]
  stats: any
  active?: ModelEntry
}

export async function fetchModels(): Promise<ModelListResponse> {
  const res = await authed("GET", "/api/models/list")
  if (!res.ok) throw new Error("models list " + res.status)
  return res.json()
}

export async function activateModel(modelId: string): Promise<{ ok: boolean }> {
  const res = await authed("POST", `/api/models/activate/${modelId}`)
  if (!res.ok) throw new Error("model activate " + res.status)
  return res.json()
}

// ── 文件上传（C 阶段 1：支持图片/音频/文本/任意二进制）────
// POST  /api/file/upload  →  JSON { name, content_base64, mime_type, size }
// GET   /api/file/preview/<stored_name> → 二进制文件预览

export interface FileUploadResult {
  ok: boolean
  path: string
  ref: string
  name: string
  mime_type: string
  size: number
  is_image: boolean
  preview_url: string | null
  error?: string
}

export async function uploadFile(file: File): Promise<FileUploadResult> {
  const token = await getToken()
  // 读文件内容 → base64
  const buf = await file.arrayBuffer()
  const bytes = new Uint8Array(buf)
  let binary = ""
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i])
  }
  const content_base64 = btoa(binary)
  const res = await fetch(apiBase() + "/api/file/upload", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({
      name: file.name,
      content_base64,
      mime_type: file.type || "application/octet-stream",
      size: file.size,
    }),
  })
  if (!res.ok) throw new Error("file upload " + res.status)
  return res.json()
}

// 前端的 base64 → Blob URL（用于粘贴截图本地预览，不等上传）
export function blobToDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result as string)
    reader.onerror = reject
    reader.readAsDataURL(blob)
  })
}

// ── Token 用量统计（2026-07-26 Phase 0）────────────────────────
export interface UsageStats {
  status: string;
  window_days?: number;
  total: { prompt_tokens: number; completion_tokens: number; total_tokens: number; calls: number; est_cost_cny: number | null };
  today: { total_tokens: number; calls: number };
  by_model: { model: string; provider: string; total_tokens: number; calls: number; est_cost_cny: number | null }[];
  by_day: { date: string; total_tokens: number }[];
  by_source: { source: string; total_tokens: number; calls: number }[];
}
export async function fetchUsageStats(): Promise<UsageStats> {
  const res = await authed("GET", "/api/usage/stats")
  if (!res.ok) throw new Error("usage stats " + res.status)
  return res.json()
}
export interface UsageItem {
  ts: number; session: string; model: string; provider: string; source: string;
  prompt_tokens: number; completion_tokens: number; total_tokens: number;
}
export async function fetchUsageRecent(limit = 20): Promise<UsageItem[]> {
  const res = await authed("GET", `/api/usage/recent?limit=${limit}`)
  if (!res.ok) throw new Error("usage recent " + res.status)
  const data = await res.json()
  return data.items || []
}

// ── 画布节点目录（NodePalette 拖拽，2026-07-26 Phase 0）────────
export interface NodeTypeDef {
  type: string; label: string; icon: string; color: string; description: string;
  defaultData: Record<string, any>;
  configSchema: { key: string; label: string; kind: string; required?: boolean; options?: string[] }[];
}
export interface ToolInstanceDef {
  nodeType: string; id: string; label: string; source: string; description: string;
  data: Record<string, any>;
}
export interface NodeCatalog {
  status: string; nodeTypes: NodeTypeDef[]; toolInstances: ToolInstanceDef[];
}
export async function fetchNodeCatalog(): Promise<NodeCatalog> {
  const res = await authed("GET", "/api/canvas/node-catalog")
  if (!res.ok) throw new Error("node catalog " + res.status)
  return res.json()
}

// ── 验收调试台（界面驱动黑盒调试员模式，2026-07-27 Phase 2）────────
// GET  /api/acceptance         → 实时六维快照（live 信号 + 最近一次探针结论）
// GET  /api/acceptance/history → 验收账本历史（?limit=20，反序切片）
// POST /api/acceptance/run     → 触发三套只读黑盒探针跑批，写入账本（限频 60s）

export type AcceptanceStatus = "pass" | "warn" | "partial" | "fail" | "unknown";

export interface AcceptanceDim {
  key: string;
  cn: string;
  status: AcceptanceStatus;
  score: number;
  source: string; // "probe" | "live" | "ledger"
  detail: string;
}

export interface AcceptanceOverall {
  score: number;
  status: AcceptanceStatus;
}

export interface AcceptanceSnapshot {
  ts: number;
  ts_human: string;
  mode: string;
  overall: AcceptanceOverall;
  dims: AcceptanceDim[];
  last_run: string | null;
  note: string;
}

export interface AcceptanceProbe {
  ok: boolean | null;
  summary?: any;
}

export interface AcceptanceRecord {
  ts: number;
  ts_human: string;
  overall: AcceptanceOverall;
  dims: AcceptanceDim[];
  probes?: Record<string, AcceptanceProbe>;
}

export interface AcceptanceHistory {
  count: number;
  runs: AcceptanceRecord[];
}

export async function fetchAcceptance(): Promise<AcceptanceSnapshot> {
  const res = await authed("GET", "/api/acceptance");
  if (!res.ok) throw new Error("acceptance " + res.status);
  return res.json();
}

export async function fetchAcceptanceHistory(limit = 20): Promise<AcceptanceHistory> {
  const res = await authed("GET", `/api/acceptance/history?limit=${limit}`);
  if (!res.ok) throw new Error("acceptance history " + res.status);
  return res.json();
}

// ---- Agent 协作室（多 Agent 同室协作，Buzz 理念本地化）----
export interface RoomAgent {
  id: string; name: string; role: string;
  system_prompt: string; color: string; model: string;
}
export interface RoomMessage {
  speaker: string; role: string; text: string; ts: number; agent_id?: string;
}
export interface RoomSummary {
  id: string; name: string; agent_count: number; canvas_id: string; messages: number;
}
export interface RoomDetail {
  id: string; name: string; canvas_id: string;
  agents: RoomAgent[]; transcript: RoomMessage[];
}

export async function fetchAgentRooms(): Promise<RoomSummary[]> {
  const res = await authed("GET", "/api/agent_rooms");
  if (!res.ok) throw new Error("agent_rooms " + res.status);
  return (await res.json()).rooms || [];
}

export async function fetchAgentRoom(id: string): Promise<RoomDetail> {
  const res = await authed("GET", `/api/agent_rooms/${encodeURIComponent(id)}`);
  if (!res.ok) throw new Error("agent_room " + res.status);
  return res.json();
}

export async function createAgentRoom(
  name: string,
  agents: Array<Partial<RoomAgent>>,
  canvasId = "",
): Promise<{ id: string; name: string; agents: number }> {
  const token = await getToken();
  const res = await fetch(apiBase() + "/api/agent_rooms", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({ name, agents, canvas_id: canvasId }),
  });
  if (!res.ok) {
    let msg = "HTTP " + res.status;
    try { msg = (await res.json()).error || msg; } catch {}
    throw new Error(msg);
  }
  return res.json();
}

export async function deleteAgentRoom(id: string): Promise<void> {
  const res = await authed("DELETE", `/api/agent_rooms/${encodeURIComponent(id)}`);
  if (!res.ok) throw new Error("delete room " + res.status);
}

export async function resetAgentRoom(id: string): Promise<void> {
  const res = await authed("POST", `/api/agent_rooms/${encodeURIComponent(id)}/reset`);
  if (!res.ok) throw new Error("reset room " + res.status);
}

/** 发起一轮多 Agent 协作，返回完整 transcript（同步等待全部 Agent 发言完毕）。 */
export async function sendAgentRoomMessage(id: string, text: string): Promise<RoomDetail> {
  const token = await getToken();
  const res = await fetch(apiBase() + `/api/agent_rooms/${encodeURIComponent(id)}/message`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Auth-Token": token },
    body: JSON.stringify({ text }),
  });
  if (!res.ok) {
    let msg = "HTTP " + res.status;
    try { msg = (await res.json()).error || msg; } catch {}
    throw new Error(msg);
  }
  return res.json();
}

export async function runAcceptance(): Promise<AcceptanceRecord> {
  const res = await authed("POST", "/api/acceptance/run");
  if (res.status === 429) {
    let d: any = {};
    try { d = await res.json(); } catch {}
    const err: any = new Error(d.error || "限频中，请稍后再试");
    err.retryAfter = d.retry_after;
    throw err;
  }
  if (!res.ok) {
    let msg = "HTTP " + res.status;
    try { msg = (await res.json()).error || msg; } catch {}
    throw new Error(msg);
  }
  return res.json();
}
