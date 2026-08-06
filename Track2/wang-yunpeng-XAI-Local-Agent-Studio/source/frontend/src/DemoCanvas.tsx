// DemoCanvas — Chat-Canvas 共創原型 (Phase 1)
// 双栏布局：左侧对话 + 右侧交互画布。独立实验页，不影响 ChatConsole。
import { useCallback, useEffect, useRef, useState } from "react";
import ReactFlow, {
  Background, Controls, Node, Edge, MarkerType,
  useNodesState, useEdgesState, addEdge, Connection,
} from "reactflow";
import "reactflow/dist/style.css";
import {
  Send, Loader2, Trash2 as Trash,
  MessageSquare, Bot, User, Network, Sparkles, X,
} from "lucide-react";
import {
  sendChat, fetchAgents, fetchCapabilities,
  type ChatEvent, type AgentInfo,
} from "./lib/api";
import { ProgressIndicator, buildProgressInfo } from "./ProgressIndicator";

// ---- 节点类型定义 ----
const NODE_TYPES: Record<string, { label: string; bg: string; border: string }> = {
  agent:   { label: "Agent",   bg: "#eff6ff", border: "#3b82f6" },
  tool:    { label: "Tool",    bg: "#ecfdf5", border: "#10b981" },
  code:    { label: "Code",    bg: "#1e1e2e", border: "#a78bfa" },
  text:    { label: "Text",    bg: "#fefce8", border: "#eab308" },
  memory:  { label: "Memory",  bg: "#fdf2f8", border: "#ec4899" },
  result:  { label: "Result",  bg: "#f0fdf4", border: "#22c55e" },
};

// ---- 对话消息类型 ----
interface DemoMsg {
  id: string; role: "user" | "assistant";
  content: string; thinking: string[];
  intent: string | null; done: boolean;
  events: Array<{ type: string; [k: string]: any }>;
}

// ---- 主组件 ----
export default function DemoCanvas() {
  // 布局
  const [split, setSplit] = useState(42); // 左栏 %
  const dragging = useRef(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // 对话
  const [msgs, setMsgs] = useState<DemoMsg[]>([{
    id: "welcome", role: "assistant", content:
      "欢迎来到 Chat-Canvas 共創原型。\n\n在左侧对话中描述你的任务，AI 回复后点击「同步到画布」可将结构化内容转为右侧可视化节点。你可以拖拽、连线、编辑节点，形成执行流程。",
    thinking: [], intent: null, done: true, events: [],
  }]);
  const [input, setInput] = useState("");
  const [thinking, setThinking] = useState(false);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  // 画布
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [canvasSel, setCanvasSel] = useState<string | null>(null);
  const nodeCounter = useRef(0);
  let _nid = () => `node_${++nodeCounter.current}`;
  let _mid = () => `msg_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;

  // 拖拽分隔线
  const onDividerDown = useCallback(() => { dragging.current = true; }, []);
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!dragging.current || !containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      const pct = ((e.clientX - rect.left) / rect.width) * 100;
      setSplit(Math.max(25, Math.min(65, pct)));
    };
    const onUp = () => { dragging.current = false; };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => { window.removeEventListener("mousemove", onMove); window.removeEventListener("mouseup", onUp); };
  }, []);

  useEffect(() => { chatEndRef.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs]);

  // ---- 对话发送 ----
  const doSend = useCallback(async () => {
    const text = input.trim();
    if (!text || thinking) return;
    setInput("");
    const uMsg: DemoMsg = { id: _mid(), role: "user", content: text, thinking: [], intent: null, done: true, events: [] };
    const aMsg: DemoMsg = { id: _mid(), role: "assistant", content: "", thinking: [], intent: null, done: false, events: [] };
    setMsgs((p) => [...p, uMsg, aMsg]);
    setThinking(true);
    const ac = new AbortController();
    abortRef.current = ac;
    try {
      await sendChat({
        text, kernel: "", session: "default", signal: ac.signal,
        onEvent: (ev: ChatEvent) => {
          if (ac.signal.aborted) return;
          setMsgs((p) => p.map((m) => {
            if (m.id !== aMsg.id) return m;
            const t = [...m.thinking];
            if (ev.type === "thought") t.push(ev.text || ev.content || "");
            return {
              ...m,
              content: (ev.type === "token" || ev.type === "answer")
                ? m.content + (ev.text || ev.content || "")
                : m.content,
              thinking: t,
              intent: ev.type === "intent" ? (ev.intent || ev.text || "") : m.intent,
              events: [...m.events, ev],
              done: ev.type === "done",
            };
          }));
        },
      });
    } catch { /* 中断或错误静默 */ }
    finally { setThinking(false); abortRef.current = null; }
  }, [input, thinking]);

  const doStop = () => { abortRef.current?.abort(); };

  // ---- 画布操作 ----
  const addNode = (type: string, label: string, extra?: Partial<Node>) => {
    const t = NODE_TYPES[type] || NODE_TYPES.text;
    const n: Node = {
      id: _nid(), type: "default",
      position: { x: 50 + Math.random() * 300, y: 50 + nodes.length * 80 },
      data: { label, nodeType: type },
      style: { background: t.bg, border: `2px solid ${t.border}`, borderRadius: 10, padding: 10, fontSize: 12, width: 160, color: "#333" },
      ...extra,
    };
    setNodes((p) => [...p, n]);
  };

  const removeNode = (id: string) => {
    setNodes((p) => p.filter((n) => n.id !== id));
    setEdges((p) => p.filter((e) => e.source !== id && e.target !== id));
    if (canvasSel === id) setCanvasSel(null);
  };

  const onConnect = useCallback((conn: Connection) => {
    setEdges((eds) => addEdge({ ...conn, markerEnd: { type: MarkerType.ArrowClosed } }, eds));
  }, [setEdges]);

  // 加载后端数据到画布
  const loadAgentsToCanvas = async () => {
    try {
      const agents = await fetchAgents();
      agents.forEach((a, i) => addNode("agent", `${a.name}\n${a.role} · ${a.backend}`, {
        position: { x: 50, y: 20 + i * 90 },
      }));
    } catch { /* ignore */ }
  };

  const loadCapabilitiesToCanvas = async () => {
    try {
      const caps = await fetchCapabilities();
      caps.forEach((c: any, i: number) => {
        addNode("tool", `${c.name || c.id}\n${(c.desc || "").slice(0, 40)}`, {
          position: { x: 280, y: 20 + i * 80 },
        });
      });
    } catch { /* ignore */ }
  };

  // AI 回复 → 画布
  const syncToCanvas = (content: string) => {
    // 提取代码块
    const codeBlocks = content.match(/```(\w*)\n([\s\S]*?)```/g);
    if (codeBlocks) {
      codeBlocks.forEach((cb) => {
        const lang = cb.match(/```(\w*)/)?.[1] || "";
        addNode("code", `Code (${lang || "plain"})\n${cb.slice(0, 80)}...`);
      });
    }
    // 提取结构化行（以 - 或数字开头的列表）
    const lines = content.split("\n").filter((l) => /^[\-\d]+[.\)]\s/.test(l.trim()));
    if (lines.length > 0) {
      addNode("text", `要点 (${lines.length} 条)\n${lines.slice(0, 3).join("\n")}`);
    }
    // 没有结构化内容 → 整体作为文本节点
    if (!codeBlocks && lines.length === 0 && content.length > 20) {
      addNode("text", content.slice(0, 120) + (content.length > 120 ? "…" : ""));
    }
  };

  // ---- 渲染 ----
  return (
    <div ref={containerRef} className="h-full flex flex-col bg-zinc-50 dark:bg-zinc-950">
      {/* 顶部工具栏 */}
      <div className="flex items-center gap-2 px-4 py-2 border-b border-zinc-200 dark:border-zinc-800 text-xs shrink-0">
        <Sparkles size={14} className="text-purple-500" />
        <span className="font-medium">Chat-Canvas 共創</span>
        <span className="text-zinc-400">| 实验版 — 不���响现有功能</span>
        <div className="ml-auto flex items-center gap-2">
          <button onClick={loadAgentsToCanvas}
            className="px-2 py-1 rounded text-[11px] bg-blue-50 dark:bg-blue-950 text-blue-600 dark:text-blue-400 hover:bg-blue-100">
            + Agent 节点
          </button>
          <button onClick={loadCapabilitiesToCanvas}
            className="px-2 py-1 rounded text-[11px] bg-emerald-50 dark:bg-emerald-950 text-emerald-600 dark:text-emerald-400 hover:bg-emerald-100">
            + 能力节点
          </button>
          <button onClick={() => { setNodes([]); setEdges([]); }}
            className="px-2 py-1 rounded text-[11px] text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800">
            清空画布
          </button>
          <span className="text-zinc-400 ml-2">
            节点 {nodes.length} · 连线 {edges.length}
            {canvasSel ? ` · 选中 ${canvasSel}` : ""}
          </span>
        </div>
      </div>

      {/* 双栏主体 */}
      <div className="flex-1 flex overflow-hidden" style={{ cursor: dragging.current ? "col-resize" : undefined }}>
        {/* 左栏：对话 */}
        <div className="flex flex-col overflow-hidden border-r border-zinc-200 dark:border-zinc-800" style={{ width: `${split}%` }}>
          <div className="px-3 py-2 border-b border-zinc-100 dark:border-zinc-800 text-[11px] text-zinc-400 flex items-center gap-2 shrink-0">
            <MessageSquare size={12} /> 对话栏
            <span className="ml-auto">Enter 发送 · Esc 中断</span>
          </div>
          <div className="flex-1 overflow-auto px-3 py-2 space-y-3">
            {msgs.map((m) => (
              <div key={m.id}>
                <div className={`flex gap-2 ${m.role === "user" ? "justify-end" : ""}`}>
                  <div className={`shrink-0 w-6 h-6 rounded-full flex items-center justify-center ${m.role === "user" ? "bg-blue-500 order-2" : "bg-zinc-300 dark:bg-zinc-700"}`}>
                    {m.role === "user" ? <User size={12} className="text-white" /> : <Bot size={12} className="text-zinc-500" />}
                  </div>
                  <div className="max-w-[85%] space-y-2">
                    {!m.done && m.events.length > 0 && (
                      <ProgressIndicator progress={buildProgressInfo(m.events)} compact />
                    )}
                    <div className={`rounded-xl px-3 py-2 text-[13px] leading-relaxed ${
                      m.role === "user"
                        ? "bg-blue-500 text-white"
                        : "bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 text-zinc-700 dark:text-zinc-200"
                    }`}>
                      {m.content ? (
                        <div className="whitespace-pre-wrap break-words">{m.content}</div>
                      ) : !m.done ? (
                        <div className="flex items-center gap-2 text-zinc-400"><Loader2 size={12} className="animate-spin" />思考中…</div>
                      ) : null}
                    {/* 思考链 */}
                    {m.thinking.length > 0 && (
                      <details className="mt-2">
                        <summary className="text-[11px] text-zinc-400 cursor-pointer">思考链 ({m.thinking.length})</summary>
                        <div className="mt-1 text-[11px] text-zinc-400 space-y-1 max-h-32 overflow-auto">
                          {m.thinking.map((t, i) => <div key={i} className="pl-2 border-l-2 border-zinc-200">{t.slice(0, 200)}</div>)}
                        </div>
                      </details>
                    )}
                    {/* 意图标签 */}
                    {m.intent && <div className="mt-1 text-[10px] text-zinc-400">意图: {m.intent}</div>}
                  </div>
                  </div>
                </div>
                {/* 同步到画布按钮 */}
                {m.role === "assistant" && m.done && m.content && (
                  <div className="flex justify-start mt-1 ml-8">
                    <button onClick={() => syncToCanvas(m.content)}
                      className="flex items-center gap-1 text-[10px] text-purple-500 hover:text-purple-700 px-2 py-0.5 rounded hover:bg-purple-50 dark:hover:bg-purple-950">
                      <Network size={10} /> 同步到画布
                    </button>
                  </div>
                )}
              </div>
            ))}
            <div ref={chatEndRef} />
          </div>

          {/* 输入框 */}
          <div className="p-3 border-t border-zinc-200 dark:border-zinc-800 shrink-0">
            <div className="flex gap-2">
              <textarea
                value={input} onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); doSend(); } else if (e.key === "Escape") { doStop(); } }}
                placeholder="描述你的任务… (Enter 发送, Shift+Enter 换行, Esc 中断)"
                rows={2}
                className="flex-1 resize-none rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-3 py-2 text-sm outline-none focus:border-purple-400"
              />
              <button onClick={thinking ? doStop : doSend}
                disabled={!input.trim() && !thinking}
                className={`shrink-0 w-10 h-10 rounded-lg flex items-center justify-center transition-colors ${
                  thinking
                    ? "bg-red-500 hover:bg-red-600 text-white"
                    : "bg-purple-500 hover:bg-purple-600 text-white disabled:opacity-30"
                }`}>
                {thinking ? <X size={16} /> : <Send size={16} />}
              </button>
            </div>
          </div>
        </div>

        {/* 可拖拽分隔线 */}
        <div onMouseDown={onDividerDown}
          className="w-2 shrink-0 bg-zinc-200 dark:bg-zinc-800 hover:bg-purple-400 cursor-col-resize transition-colors flex items-center justify-center">
          <div className="w-0.5 h-8 rounded bg-zinc-400" />
        </div>

        {/* 右栏：画布 */}
        <div className="flex-1 flex flex-col overflow-hidden" style={{ width: `${100 - split - 0.5}%` }}>
          <div className="px-3 py-2 border-b border-zinc-200 dark:border-zinc-800 text-[11px] text-zinc-400 flex items-center gap-2 shrink-0">
            <Network size={12} /> 交互画布
            <span className="ml-auto text-zinc-300">拖拽节点 · 连线编排 · 右键删除</span>
          </div>
          <div className="flex-1">
            <ReactFlow
              nodes={nodes} edges={edges}
              onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
              onConnect={onConnect}
              onNodeClick={(_, n) => setCanvasSel(n.id)}
              onPaneClick={() => setCanvasSel(null)}
              fitView
              deleteKeyCode="Delete"
              multiSelectionKeyCode="Shift"
            >
              <Background gap={20} />
              <Controls />
            </ReactFlow>
          </div>
          {/* 选中节点属性 */}
          {canvasSel && (
            <div className="px-3 py-2 border-t border-zinc-200 dark:border-zinc-800 text-[11px] flex items-center gap-2 shrink-0 bg-white dark:bg-zinc-900">
              <span className="text-zinc-400">选中:</span>
              <span className="font-mono">{canvasSel}</span>
              <span className="text-zinc-400 ml-2">
                {(() => { const n = nodes.find(x => x.id === canvasSel); return n ? NODE_TYPES[(n.data as any)?.nodeType]?.label || "节点" : "?"; })()}
              </span>
              <button onClick={() => removeNode(canvasSel)}
                className="ml-auto flex items-center gap-1 text-red-500 hover:bg-red-50 dark:hover:bg-red-950 px-2 py-0.5 rounded">
                <Trash size={11} /> 删除
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
