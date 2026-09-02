// 交互式画布——共享组件（Phase1: 节点状态+看板+执行联动）
// 被 ChatConsole/DemoCanvas/GrokConsole 复用
import { useCallback, useEffect, useRef, useState } from "react"
import ReactFlow, { Background, Controls, useNodesState, useEdgesState, addEdge, MarkerType, useReactFlow, ReactFlowProvider, type Connection, type NodeMouseHandler } from "reactflow"
import "reactflow/dist/style.css"
import type { CanvasData } from "./lib/api"

const TYPE_COLOR: Record<string, string> = { agent: "#8b5cf6", tool: "#06b6d4", memory: "#f59e0b", text: "#64748b" }
const STATUS_COLOR: Record<string, string> = {
  idle: "var(--color-border-subtle)", pending: "#3b82f6",
  running: "#f59e0b", done: "#22c55e", failed: "#ef4444", failed_guardian: "#8b5cf6",
}
const STATUS_LABEL: Record<string, string> = {
  idle: "待命", pending: "等待中", running: "执行中", done: "完成", failed: "失败", failed_guardian: "需审批",
}

// CanvasCore —— 全站唯一的交互式画布渲染内核（DAG + Kanban 双视图）。
// ChatConsole / GrokConsole / DemoCanvas 的画布右栏 / TaskCanvas 拓扑均复用本组件。
// readOnly: 仅展示、禁编辑（用于只读拓扑/共享画布视图）。
// styleMode="fixed": 直接使用节点自带的 data.style，不再套用全局 TYPE/STATUS 配色
//   （用于需要精确保留业务自定义样式的场景，如 TaskCanvas 智能任务地图）。
export function MiniCanvas(props: {
  nodes: CanvasData["nodes"]; edges: CanvasData["edges"];
  onPersist: (data: { nodes: any[]; edges: any[] }) => void;
  viewMode?: "dag" | "kanban";
  onViewModeChange?: (m: "dag" | "kanban") => void;
  onExecuteNode?: (nodeId: string, data: any) => void;
  onAddToChat?: (nodeId: string, data: any) => void;
  runningNodes?: Set<string>;
  readOnly?: boolean;
  styleMode?: "auto" | "fixed";
}) {
  return <ReactFlowProvider><MiniCanvasInner {...props} /></ReactFlowProvider>
}

function MiniCanvasInner({ nodes, edges, onPersist, viewMode, onViewModeChange, onExecuteNode, onAddToChat, runningNodes, readOnly, styleMode }: {
  nodes: CanvasData["nodes"]; edges: CanvasData["edges"];
  onPersist: (data: { nodes: any[]; edges: any[] }) => void;
  viewMode?: "dag" | "kanban";
  onViewModeChange?: (m: "dag" | "kanban") => void;
  onExecuteNode?: (nodeId: string, data: any) => void;
  onAddToChat?: (nodeId: string, data: any) => void;
  runningNodes?: Set<string>;
  readOnly?: boolean;
  styleMode?: "auto" | "fixed";
}) {
  const isReadOnly = !!readOnly
  const vm = viewMode || "dag"
  const activeIds = runningNodes || new Set<string>()

  const DEFAULT_STYLE = { background: "var(--color-bg-input)", border: "1px solid var(--color-border-subtle)", borderRadius: 10, padding: 8, fontSize: 12, width: 150, color: "var(--color-text)" } as const

  // 节点 status 着色
  const nodeStyle = (n: any) => {
    const st = n.data?.status || "idle"
    const base = { ...DEFAULT_STYLE, borderLeft: `3px solid ${TYPE_COLOR[n.data?.nodeType] || TYPE_COLOR.text}` }
    if (st === "running") return { ...base, boxShadow: "0 0 8px rgba(245,158,11,0.5)", animation: "pulse-border 1.2s ease-in-out infinite" }
    if (st !== "idle") return { ...base, borderLeft: `3px solid ${STATUS_COLOR[st] || STATUS_COLOR.idle}` }
    return base
  }

  const enrich = (n: any) => {
    // fixed 模式：精确保留节点自带样式（如 TaskCanvas 业务配色），不套全局配色
    if (styleMode === "fixed") {
      return { id: String(n.id), position: n.position || { x: 0, y: 0 }, type: "default", data: n.data || {}, style: n.style }
    }
    const data = { status: "idle", ...(n.data || {}), label: n.data?.label || String(n.id) }
    if (activeIds.has(String(n.id))) data.status = "running"
    return { id: String(n.id), position: n.position || { x: 0, y: 0 }, type: "default", data, style: nodeStyle(n) }
  }

  const [rfNodes, setRfNodes, onNodesChange] = useNodesState<any>((nodes || []).map(enrich))
  const [rfEdges, setRfEdges, onEdgesChange] = useEdgesState((edges || []).map((e, i) => ({
    id: String(e.id ?? "e" + i), source: String(e.source), target: String(e.target), markerEnd: { type: MarkerType.ArrowClosed },
  })))
  const [menu, setMenu] = useState<{ x: number; y: number; nodeId: string } | null>(null)
  const [connectSrc, setConnectSrc] = useState<string | null>(null)
  const [configNode, setConfigNode] = useState<string | null>(null)
  const { screenToFlowPosition } = useReactFlow()
  const nodesRef = useRef(rfNodes); nodesRef.current = rfNodes
  const edgesRef = useRef(rfEdges); edgesRef.current = rfEdges

  useEffect(() => {
    setRfNodes((prev) => (prev.length !== (nodes || []).length ? (nodes || []).map(enrich) : prev))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodes])

  const persist = useCallback(() => { onPersist({ nodes: nodesRef.current, edges: edgesRef.current }) }, [onPersist])
  const onConnect = useCallback((c: Connection) => {
    if (isReadOnly) return
    setRfEdges((eds) => addEdge({ ...c, markerEnd: { type: MarkerType.ArrowClosed } }, eds)); setTimeout(persist, 0)
  }, [persist, isReadOnly])
  const onNodeDragStop = useCallback(() => { if (isReadOnly) return; setTimeout(persist, 0) }, [persist, isReadOnly])

  // Phase0 drag&drop
  const onDragOver = useCallback((e: React.DragEvent) => {
    if (isReadOnly) return
    if (e.dataTransfer.types.includes("application/xai-node")) { e.preventDefault(); e.dataTransfer.dropEffect = "copy" }
  }, [isReadOnly])
  const onDrop = useCallback((e: React.DragEvent) => {
    if (isReadOnly) return
    const raw = e.dataTransfer.getData("application/xai-node"); if (!raw) return
    e.preventDefault()
    let spec: any; try { spec = JSON.parse(raw) } catch { return }
    const pos = screenToFlowPosition({ x: e.clientX, y: e.clientY })
    const nodeType = spec.nodeType || "text"
    const id = "n_" + Date.now()
    setRfNodes((ns) => ns.concat({
      id, position: pos, type: "default",
      data: { label: spec.label || nodeType, nodeType, status: "idle", ...(spec.data || {}) },
      style: { ...DEFAULT_STYLE, borderLeft: `3px solid ${TYPE_COLOR[nodeType] || TYPE_COLOR.text}` },
    } as any)); setTimeout(persist, 0)
  }, [screenToFlowPosition, persist, isReadOnly])

  const onCtx: NodeMouseHandler = useCallback((e, node) => {
    if (isReadOnly) return
    e.preventDefault(); setMenu({ x: e.clientX, y: e.clientY, nodeId: node.id })
  }, [isReadOnly])
  const onNodeClick: NodeMouseHandler = useCallback((_e, node) => {
    if (connectSrc && node.id !== connectSrc) {
      setRfEdges((eds) => addEdge({ id: "e_" + Date.now(), source: connectSrc, target: node.id, markerEnd: { type: MarkerType.ArrowClosed } }, eds))
      setConnectSrc(null); setTimeout(persist, 0)
    }
  }, [connectSrc, persist])
  useEffect(() => {
    if (!connectSrc) return
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setConnectSrc(null) }
    window.addEventListener("keydown", onKey); return () => window.removeEventListener("keydown", onKey)
  }, [connectSrc])

  const editLabel = (id: string) => {
    const n = rfNodes.find((n) => n.id === id)
    const t = window.prompt("编辑标签：", (n?.data?.label as string) || "")
    if (t != null) { setRfNodes((ns) => ns.map((n) => (n.id === id ? { ...n, data: { ...n.data, label: t } } : n))); setTimeout(persist, 0) }
    setMenu(null)
  }
  const runNode = (id: string) => { setMenu(null); const n = rfNodes.find((n) => n.id === id); if (n && onExecuteNode) onExecuteNode(id, n.data) }
  const addToChat = (id: string) => { setMenu(null); const n = rfNodes.find((n) => n.id === id); if (n && onAddToChat) onAddToChat(id, n.data) }
  const changeStatus = (id: string, st: string) => {
    setRfNodes((ns) => ns.map((n) => (n.id === id ? { ...n, data: { ...n.data, status: st } } : n)))
    setMenu(null); setTimeout(persist, 0)
  }
  const deleteNode = (id: string) => {
    setRfNodes((ns) => ns.filter((n) => n.id !== id))
    setRfEdges((eds) => eds.filter((e) => e.source !== id && e.target !== id))
    if (configNode === id) setConfigNode(null)
    setMenu(null); setTimeout(persist, 0)
  }

  // Kanban: 按 status 分组
  const kanbanCols = [
    { key: "idle", label: "待执行", nodes: rfNodes.filter((n) => (n.data?.status || "idle") === "idle") },
    { key: "running", label: "执行中", nodes: rfNodes.filter((n) => (n.data?.status || "idle") === "running" || activeIds.has(n.id)) },
    { key: "done", label: "已完成", nodes: rfNodes.filter((n) => (n.data?.status || "idle") === "done") },
    { key: "failed", label: "失败", nodes: rfNodes.filter((n) => (n.data?.status || "idle") === "failed" || (n.data?.status || "idle") === "failed_guardian") },
  ]

  if (vm === "kanban") {
    return (
      <div style={{ width: "100%", height: "100%", display: "flex", gap: 2, overflow: "auto", padding: 4 }}>
        {kanbanCols.map((col) => (
          <div key={col.key} style={{ flex: 1, minWidth: 160, display: "flex", flexDirection: "column", gap: 4 }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: "var(--color-text-subtle)", padding: "4px 8px", background: "var(--color-bg-elevated)", borderRadius: 8, border: "1px solid var(--color-border-subtle)", display: "flex", justifyContent: "space-between" }}>
              {col.label} <span style={{ color: "var(--color-text-muted)", fontWeight: 400 }}>{col.nodes.length}</span>
            </div>
            {col.nodes.map((n) => {
              const st = n.data?.status || "idle"
              const isRunning = st === "running" || activeIds.has(n.id)
              return (
                <div key={n.id} draggable onDragStart={(e) => { e.dataTransfer.setData("text/plain", n.id); (e.target as HTMLElement).dataset.dragStatus = st }} title={n.data?.label || n.id}
                  style={{
                    padding: "8px 10px", borderRadius: 10, fontSize: 11.5, cursor: "pointer",
                    background: "var(--color-bg-input)", border: `2px solid ${STATUS_COLOR[st] || STATUS_COLOR.idle}`,
                    color: "var(--color-text)", lineHeight: 1.4,
                    boxShadow: isRunning ? "0 0 6px rgba(245,158,11,0.4)" : undefined,
                    animation: isRunning ? "pulse-border 1.2s ease-in-out infinite" : undefined,
                  }}
                  onContextMenu={(e) => { e.preventDefault(); setMenu({ x: e.clientX, y: e.clientY, nodeId: n.id }) }}
                  onClick={() => setConfigNode(n.id)}
                >
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <span style={{ fontWeight: 500 }}>{n.data?.label || n.id}</span>
                    <span style={{ fontSize: 9, color: STATUS_COLOR[st], background: `${STATUS_COLOR[st]}22`, padding: "1px 5px", borderRadius: 4 }}>{STATUS_LABEL[st] || st}</span>
                  </div>
                  {n.data?.assignee && <div style={{ fontSize: 9.5, color: "var(--color-text-muted)", marginTop: 2 }}>👤 {n.data.assignee}</div>}
                  {n.data?.tokenUsage && <div style={{ fontSize: 9, color: "var(--color-text-muted)", marginTop: 2 }}>↑{(n.data.tokenUsage.prompt_tokens / 1000).toFixed(1)}k ↓{(n.data.tokenUsage.completion_tokens / 1000).toFixed(1)}k</div>}
                </div>
              )
            })}
          </div>
        ))}
        {menu && (
          <div style={{ position: "fixed", left: menu.x, top: menu.y, zIndex: 1000, background: "var(--color-bg-elevated)", border: "1px solid var(--color-border-subtle)", borderRadius: 10, boxShadow: "0 8px 24px rgba(0,0,0,.2)", padding: 4, minWidth: 150 }}>
            <CtxItem onClick={() => runNode(menu.nodeId)}>▶ 执行此节点</CtxItem>
            <CtxItem onClick={() => addToChat(menu.nodeId)}>💬 加入对话</CtxItem>
            <CtxItem onClick={() => { setConfigNode(menu.nodeId); setMenu(null) }}>⚙ 配置节点</CtxItem>
            <CtxItem onClick={() => editLabel(menu.nodeId)}>编辑标签</CtxItem>
            <CtxItem onClick={() => changeStatus(menu.nodeId, "idle")}>重置为待执行</CtxItem>
            <CtxItem onClick={() => deleteNode(menu.nodeId)} danger>删除</CtxItem>
          </div>
        )}
        {configNode && (() => { const node = rfNodes.find((n) => n.id === configNode); if (!node) return null; return <NodeConfigPanel node={node} onClose={() => setConfigNode(null)} onSave={(data: any) => { setRfNodes((ns) => ns.map((n) => (n.id === configNode ? { ...n, data } : n))); setConfigNode(null); setTimeout(persist, 0) }} /> })()}
      </div>
    )
  }

  // DAG view
  return (
    <div style={{ width: "100%", height: "100%", position: "relative" }}>
      {connectSrc && (
        <div style={{ position: "absolute", top: 8, left: "50%", transform: "translateX(-50%)", zIndex: 500, background: "var(--color-accent)", color: "#fff", fontSize: 11, padding: "4px 10px", borderRadius: 8, boxShadow: "0 2px 8px rgba(0,0,0,.2)" }}>连线模式：点击目标节点完成（Esc 取消）</div>
      )}
      <ReactFlow nodes={rfNodes} edges={rfEdges}
        nodesDraggable={!isReadOnly} nodesConnectable={!isReadOnly} elementsSelectable={!isReadOnly}
        onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
        onConnect={onConnect} onNodeDragStop={onNodeDragStop}
        onNodeContextMenu={onCtx} onNodeClick={onNodeClick}
        onPaneClick={() => { setMenu(null); setConfigNode(null) }}
        onDragOver={onDragOver} onDrop={onDrop}
        fitView proOptions={{ hideAttribution: true }}>
        <Background /><Controls showInteractive={false} />
      </ReactFlow>
      {menu && (
        <div style={{ position: "fixed", left: menu.x, top: menu.y, zIndex: 1000, background: "var(--color-bg-elevated)", border: "1px solid var(--color-border-subtle)", borderRadius: 10, boxShadow: "0 8px 24px rgba(0,0,0,.2)", padding: 4, minWidth: 150 }}>
          <CtxItem onClick={() => runNode(menu.nodeId)}>▶ 执行此节点</CtxItem>
          <CtxItem onClick={() => addToChat(menu.nodeId)}>💬 加入对话</CtxItem>
          <CtxItem onClick={() => { setConfigNode(menu.nodeId); setMenu(null) }}>⚙ 配置节点</CtxItem>
          <CtxItem onClick={() => editLabel(menu.nodeId)}>编辑标签</CtxItem>
          <CtxItem onClick={() => { setConnectSrc(menu.nodeId); setMenu(null) }}>开始连线</CtxItem>
          <CtxItem onClick={() => deleteNode(menu.nodeId)} danger>删除</CtxItem>
        </div>
      )}
      {configNode && (() => { const node = rfNodes.find((n) => n.id === configNode); if (!node) return null; return <NodeConfigPanel node={node} onClose={() => setConfigNode(null)} onSave={(data: any) => { setRfNodes((ns) => ns.map((n) => (n.id === configNode ? { ...n, data } : n))); setConfigNode(null); setTimeout(persist, 0) }} /> })()}
    </div>
  )
}

// ---- 节点配置面板 ----
function NodeConfigPanel({ node, onClose, onSave }: { node: any; onClose: () => void; onSave: (data: any) => void }) {
  const fields = Object.entries(node.data || {}).filter(([k]) => !["nodeType"].includes(k))
  const [draft, setDraft] = useState<Record<string, string>>(
    Object.fromEntries(fields.map(([k, v]) => [k, typeof v === "string" ? v : JSON.stringify(v)]))
  )
  const nodeType = node.data?.nodeType || "text"
  const save = () => {
    const data: any = { nodeType }
    for (const [k, v] of Object.entries(draft)) { try { data[k] = JSON.parse(v) } catch { data[k] = v } }
    onSave(data)
  }
  return (
    <div style={{ position: "absolute", top: 8, right: 8, bottom: 8, width: 240, zIndex: 600, background: "var(--color-bg-elevated)", border: "1px solid var(--color-border-subtle)", borderRadius: 12, boxShadow: "0 8px 24px rgba(0,0,0,.18)", padding: 12, display: "flex", flexDirection: "column", gap: 8, overflow: "auto" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span style={{ fontSize: 12.5, fontWeight: 600, color: "var(--color-text)" }}>节点配置 <span style={{ color: TYPE_COLOR[nodeType] || "var(--color-text-subtle)", fontSize: 11 }}>({nodeType})</span></span>
        <button onClick={onClose} style={{ border: "none", background: "transparent", cursor: "pointer", color: "var(--color-text-subtle)", fontSize: 14 }}>×</button>
      </div>
      {Object.keys(draft).map((k) => (
        <label key={k} style={{ fontSize: 11, color: "var(--color-text-subtle)", display: "flex", flexDirection: "column", gap: 3 }}>{k}
          <textarea value={draft[k]} onChange={(e) => setDraft((d) => ({ ...d, [k]: e.target.value }))}
            rows={["prompt", "content", "query", "result"].includes(k) ? 4 : 1}
            placeholder={k === "schedule" ? "留空=不定时 · */5/@hourly/@daily/every 3h" : ""}
            style={{ resize: "vertical", fontSize: 12, padding: "6px 8px", borderRadius: 8, border: "1px solid var(--color-border-subtle)", background: "var(--color-bg-input)", color: "var(--color-text)", fontFamily: "inherit" }} />
        </label>
      ))}
      {Object.keys(draft).length === 0 && <div style={{ fontSize: 11.5, color: "var(--color-text-subtle)" }}>无可配置字段</div>}
      <button onClick={save} style={{ marginTop: "auto", padding: "7px 0", borderRadius: 8, border: "none", cursor: "pointer", background: "var(--color-accent)", color: "#fff", fontSize: 12.5, fontWeight: 500 }}>保存</button>
    </div>
  )
}

function CtxItem({ children, onClick, danger }: { children: React.ReactNode; onClick: () => void; danger?: boolean }) {
  return <button onClick={onClick} style={{ display: "block", width: "100%", textAlign: "left", padding: "7px 10px", borderRadius: 7, border: "none", background: "transparent", cursor: "pointer", fontSize: 12.5, color: danger ? "#ef4444" : "var(--color-text)" }}
    onMouseEnter={(e) => (e.currentTarget.style.background = "var(--color-accent-bg)")}
    onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}>{children}</button>
}
