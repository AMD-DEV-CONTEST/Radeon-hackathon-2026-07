import { useEffect, useRef, useState, useCallback } from "react"
import {
  Send, Bot, Loader2, Copy, Download, RefreshCw, ChevronDown, ChevronUp,
  Cpu, Target, ShieldCheck, Activity, ArrowDown, AlertCircle, MessageSquare,
  Sparkles, Plug, Search, Dna, HelpCircle, Network, Plus, X, Paperclip, Image as ImageIcon, File as FileIcon,
} from "lucide-react"
import ReactFlow, { Background, Controls, useNodesState, useEdgesState, addEdge, MarkerType, type Node, type Edge, type Connection, type NodeMouseHandler } from "reactflow"
import "reactflow/dist/style.css"
import { getToken, sendChat, fetchStatus, searchMemory, listSessions, getSessionMessages, deleteSession, fetchAgents, fetchCapabilities, classifyIntent, uploadFile, blobToDataUrl, fetchUsageRecent, apiBase, type ChatEvent, type MemorySearchHit, type CanvasData } from "./lib/api"
import MessageContent from "./MessageContent"
import NodePalette from "./NodePalette"
/* 交互式画布（E1/E2 配色渲染 + E3 右键菜单/连线/拖拽）——会话面板与 Grok 面板共用同一实现 */
import { MiniCanvas } from "./MiniCanvas"
import { ProgressIndicator, buildProgressInfo } from "./ProgressIndicator"
import { createSessionMeta, updateSessionMeta } from "./SessionSidebar"

/* ---------- 类型 ---------- */
type Role = "user" | "assistant"
interface ThinkingStep { stage: string; text: string }
interface IntentInfo { label: string; conf: number; rationale?: string }
interface GuardInfo { level: string; reason: string }
interface PlanStep { step_id: number; agent: string; task: string; status: string }
interface ChatMsg {
  id: number
  role: Role
  content: string
  thinking: ThinkingStep[]
  intent: IntentInfo | null
  guard: GuardInfo | null
  plan: PlanStep[]
  events: Array<{ type: string; [k: string]: any }>
  kernel: string
  done: boolean
  usage?: { prompt_tokens: number; completion_tokens: number } | null
}

// 附件（粘贴/拖拽/上传）
interface AttachedFile {
  id: string
  file: File
  name: string
  size: number
  mime_type: string
  is_image: boolean
  dataUrl: string | null
  ref: string | null     // 上传后后端返回的 @file:xx 引用
  uploading: boolean
  error: string | null
}

let _id = 0
const nextId = () => ++_id

const KERNEL_LABEL: Record<string, string> = {
  "": "自动", hermes: "Hermes", grok_build: "Grok Build",
}

const QUICK: { label: string; el: JSX.Element }[] = [
  { label: "/models", el: <Bot size={15} /> },
  { label: "/skill list", el: <Sparkles size={15} /> },
  { label: "/mcp list", el: <Plug size={15} /> },
  { label: "/scan", el: <Search size={15} /> },
  { label: "/evolve", el: <Dna size={15} /> },
  { label: "/help", el: <HelpCircle size={15} /> },
]

const EXAMPLES = [
  "用一句话自我介绍",
  "分三步处理用户请求：分类、查询、回复",
  "帮我看看当前系统状态",
]

export default function ChatConsole(props?: { currentSessionId?: string | null; onSessionChange?: (id: string) => void; activeModelVision?: boolean }) {
  const [messages, setMessages] = useState<ChatMsg[]>([])
  const [input, setInput] = useState("")
  const [isThinking, setIsThinking] = useState(false)
  const [kernel, setKernel] = useState<"" | "hermes" | "grok_build">("")
  const [routeHint, setRouteHint] = useState<string | null>(null)
  const [status, setStatus] = useState<{ engine?: string; model?: string } | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [showToBottom, setShowToBottom] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const taRef = useRef<HTMLTextAreaElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const mentionTimer = useRef<number | null>(null)
  const [mention, setMention] = useState<{ open: boolean; start: number; q: string; results: MemorySearchHit[]; active: number }>({
    open: false, start: 0, q: "", results: [], active: 0,
  })
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(props?.currentSessionId ?? null)
  const [sessionTitle, setSessionTitle] = useState("新对话")
  // 附件
  const [attachments, setAttachments] = useState<AttachedFile[]>([])
  const fileInputRef = useRef<HTMLInputElement>(null)
  // 分类上传菜单
  const [uploadMenuOpen, setUploadMenuOpen] = useState(false)
  const uploadMenuRef = useRef<HTMLDivElement>(null)
  const [fileAccept, setFileAccept] = useState("image/*,audio/*,video/*,.pdf,.txt,.md,.py,.js,.ts,.json,.csv,.yaml,.yml,.html,.css,.log")
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (uploadMenuRef.current && !uploadMenuRef.current.contains(e.target as Element)) setUploadMenuOpen(false)
    }
    if (uploadMenuOpen) document.addEventListener("mousedown", handler)
    return () => document.removeEventListener("mousedown", handler)
  }, [uploadMenuOpen])
  // 同步 prop → state + 触发加载（外部点会话时关键）
  useEffect(() => {
    const newId = props?.currentSessionId
    if (newId !== undefined && newId !== currentSessionId) {
      setCurrentSessionId(newId)
      // 同步加载该会话历史（用新 id 立即取消息，避免依赖 state 更新时机）
      if (newId) {
        getSessionMessages(newId).then((msgs) => {
          const chats: ChatMsg[] = (msgs || []).map((m, i) => ({
            id: i + 1,
            role: m.role as Role,
            content: m.content || "",
            thinking: [],
            intent: null,
            guard: null,
            plan: [],
            events: [],
            kernel: "",
            done: true,
          }))
          setMessages(chats)
          // 同步加载该会话画布（按会话隔离：存档优先，否则由本对话消息自动生成）
          loadCanvasForSession(newId, chats)
          // 加载标题
          try {
            const raw = localStorage.getItem("xai_sessions_meta")
            if (raw) {
              const m = JSON.parse(raw)
              if (m[newId]?.title && m[newId].title !== "新对话") setSessionTitle(m[newId].title)
            }
          } catch {}
        }).catch(() => { setMessages([]); loadCanvasForSession(newId, []) })
      } else {
        setMessages([])
        loadCanvasForSession(null, [])
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [props?.currentSessionId])

  const [showCanvas, setShowCanvas] = useState(false)
  const [canvas, setCanvas] = useState<CanvasData | null>(null)
  const [canvasWidth, setCanvasWidth] = useState(40) // 画布占比 %
  const [showPalette, setShowPalette] = useState(false) // 节点库抽屉（Phase 0 拖拽加载）
  const [canvasViewMode, setCanvasViewMode] = useState<"dag" | "kanban">("dag") // P1: 画布双视图
  const [runningNodes, setRunningNodes] = useState<Set<string>>(new Set()) // P1: 执行中节点
  const draggingRef = useRef(false)
  const mainAreaRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    getToken().catch(() => {})
    fetchStatus().then((s) => setStatus({ engine: s.xai_engine, model: s.model })).catch(() => {})
  }, [])

  // 画布/对话比例拖拽
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!draggingRef.current || !mainAreaRef.current) return
      const rect = mainAreaRef.current.getBoundingClientRect()
      const pct = ((e.clientX - rect.left) / rect.width) * 100
      setCanvasWidth(Math.max(20, Math.min(70, 100 - pct))) // 反转：左是 pct，右是 100-pct
    }
    const onUp = () => { draggingRef.current = false; document.body.style.cursor = ""; document.body.style.userSelect = "" }
    window.addEventListener("mousemove", onMove)
    window.addEventListener("mouseup", onUp)
    return () => { window.removeEventListener("mousemove", onMove); window.removeEventListener("mouseup", onUp) }
  }, [])

  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" })
  }, [messages, isThinking])

  // 自动模式下：输入时预分类意图，若会路由到 Grok Build 则给提示
  useEffect(() => {
    if (kernel !== "" || !input.trim()) { setRouteHint(null); return }
    const t = setTimeout(() => {
      classifyIntent(input.trim()).then((r) => {
        setRouteHint(r.kernel === "grok_build" ? "🚀 自动路由 → Grok Build（检测到代码任务）" : null)
      }).catch(() => setRouteHint(null))
    }, 400)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [input, kernel])

  const onScroll = () => {
    const el = scrollRef.current
    if (!el) return
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 60
    setShowToBottom(!atBottom)
  }

  // ───── 附件处理 ─────
  const addFile = (file: File) => {
    const isImg = file.type.startsWith("image/")
    const att: AttachedFile = {
      id: crypto.randomUUID?.() || `f${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
      file, name: file.name, size: file.size, mime_type: file.type || "application/octet-stream",
      is_image: isImg, dataUrl: null, ref: null, uploading: false, error: null,
    }
    if (isImg) {
      blobToDataUrl(file).then((url) => {
        setAttachments((prev) => prev.map((a) => a.id === att.id ? { ...a, dataUrl: url } : a))
      }).catch(() => {})
    }
    setAttachments((prev) => [...prev, att])
  }

  const removeAtt = (id: string) => {
    setAttachments((prev) => prev.filter((a) => a.id !== id))
  }

  const handlePaste = (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const items = e.clipboardData?.items
    if (!items) return
    for (let i = 0; i < items.length; i++) {
      const item = items[i]
      if (item.kind === "file") {
        e.preventDefault()
        const file = item.getAsFile()
        if (file) addFile(file)
      }
      if (item.type.startsWith("image/")) {
        e.preventDefault()
        const file = item.getAsFile()
        if (file) addFile(file)
      }
    }
    // 粘贴后自动聚焦回输入框
    setTimeout(() => taRef.current?.focus(), 50)
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    const files = e.dataTransfer?.files
    if (files) {
      for (let i = 0; i < files.length; i++) addFile(files[i])
    }
  }

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = "copy"
  }

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (files) {
      for (let i = 0; i < files.length; i++) addFile(files[i])
    }
    if (fileInputRef.current) fileInputRef.current.value = ""
  }

  const uploadAttachments = async (): Promise<string[]> => {
    const refs: string[] = []
    for (const att of attachments.filter((a) => !a.ref && !a.error)) {
      setAttachments((prev) => prev.map((a) => a.id === att.id ? { ...a, uploading: true } : a))
      try {
        const result = await uploadFile(att.file)
        const ref = result.ref
        refs.push(ref)
        setAttachments((prev) => prev.map((a) => a.id === att.id ? { ...a, ref, uploading: false } : a))
      } catch (e: any) {
        setAttachments((prev) => prev.map((a) => a.id === att.id ? { ...a, uploading: false, error: e?.message || "上传失败" } : a))
      }
    }
    for (const att of attachments) {
      if (att.ref) refs.push(att.ref)
    }
    return refs
  }

  // 输入框自动扩展高度（最多 8 行）
  useEffect(() => {
    const ta = taRef.current
    if (ta) {
      ta.style.height = "auto"
      const lineCount = Math.max(1, input.split("\n").length)
      const lineH = 21
      ta.style.height = `${Math.min(8, lineCount) * lineH + 20}px`
    }
  }, [input])

  // ---- 会话管理 ----
  const doNewSession = useCallback(() => {
    const id = crypto.randomUUID?.() || `s${Date.now()}_${Math.random().toString(36).slice(2, 7)}`
    createSessionMeta(id)
    setCurrentSessionId(id)
    setSessionTitle("新对话")
    setMessages([])
    loadCanvasForSession(null, [])
    setErr(null)
  }, [])

  const doSelectSession = useCallback(async (id: string) => {
    setCurrentSessionId(id)
    setErr(null)
    try {
      const msgs = await getSessionMessages(id)
      const chats: ChatMsg[] = msgs.map((m, i) => ({
        id: i + 1,
        role: m.role as Role,
        content: m.content || "",
        thinking: [],
        intent: null,
        guard: null,
        plan: [],
        events: [],
        kernel: "",
        done: true,
      }))
      setMessages(chats)
      // 同步加载该会话的画布（按会话隔离：存档优先，否则由本对话消息自动生成）
      loadCanvasForSession(id, chats)
      // 更新标题
      const meta = createSessionMeta(id)
      const metaRaw = localStorage.getItem("xai_sessions_meta")
      if (metaRaw) {
        try {
          const m = JSON.parse(metaRaw)
          if (m[id]?.title && m[id].title !== "新对话") setSessionTitle(m[id].title)
        } catch {}
      }
    } catch {
      setMessages([])
    }
  }, [])

  const doDeleteSession = useCallback(async (id: string) => {
    try { await deleteSession(id) } catch {}
    // 清除 localStorage
    try {
      const raw = localStorage.getItem("xai_sessions_meta")
      if (raw) {
        const metas = JSON.parse(raw)
        delete metas[id]
        localStorage.setItem("xai_sessions_meta", JSON.stringify(metas))
      }
    } catch {}
    if (currentSessionId === id) doNewSession()
  }, [currentSessionId, doNewSession])

  // 首次加载：从最近会话恢复，否则创建新会话
  useEffect(() => {
    if (currentSessionId) {
      // 已经有 sessionId 时，加载历史
      doSelectSession(currentSessionId)
      return
    }
    try {
      const raw = localStorage.getItem("xai_sessions_meta")
      if (raw) {
        const metas = JSON.parse(raw)
        const ids = Object.keys(metas)
        if (ids.length > 0) {
          const sorted = ids.sort((a, b) => (metas[b]?.lastActiveAt || 0) - (metas[a]?.lastActiveAt || 0))
          const id = sorted[0]
          setCurrentSessionId(id)
          props?.onSessionChange?.(id)
          doSelectSession(id)
          return
        }
      }
    } catch {}
    doNewSession()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const send = useCallback(async () => {
    const text = input.trim()
    // 如果没有文字但有附件，允许仅凭附件发送
    if (!text && attachments.length === 0) return
    if (isThinking) return
    // 先上传所有未上传的附件
    let fileRefs: string[] = []
    if (attachments.length > 0) {
      setErr(null)
      fileRefs = await uploadAttachments()
      const errs = attachments.filter((a) => a.error)
      if (errs.length > 0) {
        setErr(errs.map((a) => `${a.name}: ${a.error}`).join("; "))
        return
      }
    }
    // 拼接 @file:ref 到文本
    const fullText = [text, ...fileRefs.map((r) => r)].filter(Boolean).join("\n")
    setErr(null)
    setInput("")
    setAttachments([])
    const userMsg: ChatMsg = { id: nextId(), role: "user", content: fullText, thinking: [], intent: null, guard: null, plan: [], events: [], kernel, done: true }
    const aMsg: ChatMsg = { id: nextId(), role: "assistant", content: "", thinking: [], intent: null, guard: null, plan: [], events: [], kernel, done: false }
    setMessages((prev) => [...prev, userMsg, aMsg])
    setIsThinking(true)
    const ac = new AbortController()
    abortRef.current = ac
    let acc = ""
    let curIntent: IntentInfo | null = null
    let curGuard: GuardInfo | null = null
    let curPlan: PlanStep[] = []
    let curKernel: "" | "hermes" | "grok_build" = kernel
    const steps: ThinkingStep[] = []
    const eventsLog: Array<{ type: string; [k: string]: any }> = []
    const patch = () =>
      setMessages((prev) =>
        prev.map((m) => (m.id === aMsg.id ? { ...m, content: acc, thinking: [...steps], intent: curIntent, guard: curGuard, plan: curPlan, kernel: curKernel, events: [...eventsLog] } : m))
      )
    try {
      const sid = currentSessionId || (() => { const id = crypto.randomUUID?.() || `s${Date.now()}`; createSessionMeta(id); setCurrentSessionId(id); return id; })()
      let firstResponseCaptured = false
      await sendChat({
        text: fullText, kernel, session: sid, signal: ac.signal,
        onEvent: (ev: ChatEvent) => {
          eventsLog.push(ev)
          if (!firstResponseCaptured && (ev.type === "token" || ev.type === "answer")) {
            firstResponseCaptured = true
            // 自动生成标题
            const t = (ev.text || ev.answer || "").replace(/[#*`\n\r]/g, "").trim().slice(0, 30)
            if (t && sessionTitle === "新对话") {
              setSessionTitle(t)
              updateSessionMeta(sid, { title: t })
            }
          }
          switch (ev.type) {
            case "intent": curIntent = { label: ev.intent, conf: ev.confidence, rationale: ev.rationale }; break
            case "routed": curKernel = (ev.kernel === "grok_build" ? "grok_build" : "hermes"); break
            case "guard": curGuard = { level: ev.level, reason: ev.reason }; break
            case "plan": curPlan = ev.steps || []; break
            case "progress": steps.push({ stage: ev.stage, text: ev.text }); break
            case "token": acc += ev.text || ""; break
            case "answer": acc += ev.answer || ""; break
            default: break
          }
          patch()
        },
      })
    } catch (e: any) {
      acc = (acc || "…") + "\n\n⚠️ 请求失败：" + (e?.message || e)
    } finally {
      patch()
      setMessages((prev) => prev.map((m) => (m.id === aMsg.id ? { ...m, done: true } : m)))
      setIsThinking(false)
      abortRef.current = null
      // Token 用量：拉最近一条入账记录挂到本条消息（记账在后端异步完成，稍等再拉）
      setTimeout(() => {
        fetchUsageRecent(1).then((items) => {
          const u = items[0]
          if (u && Date.now() / 1000 - u.ts < 120) {
            setMessages((prev) => prev.map((m) => (m.id === aMsg.id
              ? { ...m, usage: { prompt_tokens: u.prompt_tokens, completion_tokens: u.completion_tokens } }
              : m)))
          }
        }).catch(() => {})
      }, 800)
      // P3: AI 主动布局 — 检测流程关键词，自动调 /api/canvas/validate → DAG 落画布
      const fullContent = acc || ""
      if (fullContent.length > 80 && showCanvas) {
        const hasFlow = /workflow|pipeline|工作流|执行流程|mermaid|flowchart|步骤[:：]/.test(fullContent + text)
        if (hasFlow) {
          setTimeout(async () => {
            try {
              const t = await getToken()
              const resp = await fetch(`${apiBase()}/api/canvas/validate`, {
                method: "POST",
                headers: { "Content-Type": "application/json", "X-Auth-Token": t },
                body: JSON.stringify({ description: fullContent.slice(0, 2000) }),
              })
              const d = await resp.json()
              if (d.valid && d.optimized_dag?.nodes?.length > 0) {
                const dag = d.optimized_dag
                const cnvs = canvas || { nodes: [], edges: [] }
                const existingIds = new Set(cnvs.nodes.map((n: any) => String(n.id)))
                const newNodes = dag.nodes.filter((n: any) => !existingIds.has(String(n.id))).map((n: any, i: number) => ({
                  id: String(n.id || ("auto_" + Date.now() + "_" + i)),
                  position: n.position || { x: 50, y: 20 + cnvs.nodes.length * 70 + i * 60 },
                  data: { label: n.label || n.type || "节点", nodeType: n.type || "agent", status: "idle", ...(n.config || {}) },
                  style: { background: "var(--color-bg-input)", border: "1px solid var(--color-border-subtle)", borderRadius: 10, padding: 8, fontSize: 12, width: 150, color: "var(--color-text)", borderLeft: "3px solid #8b5cf6" },
                }))
                const newEdges = (dag.edges || []).map((e: any) => ({
                  id: "auto_e_" + Date.now() + "_" + Math.random().toString(36).slice(2),
                  source: String(e.source), target: String(e.target),
                }))
                if (newNodes.length > 0) {
                  saveCanvasToSession({ nodes: [...cnvs.nodes, ...newNodes], edges: [...cnvs.edges, ...newEdges] })
                }
              }
            } catch {}
          }, 1500)
        }
      }
    }
  }, [input, isThinking, kernel, attachments])

  const stop = () => abortRef.current?.abort()

  // ---------- @ 提及记忆搜索 ----------
  const mentionPreview = (v: string): string => {
    const s = (v || "").trim()
    if (s.startsWith("{") || s.startsWith("[")) {
      try {
        const o = JSON.parse(s)
        const flat = Object.values(o)
          .map((x) => (typeof x === "string" ? x : JSON.stringify(x)))
          .join(" ")
        return flat.slice(0, 64)
      } catch { /* 回退原始字符串 */ }
    }
    return s.slice(0, 64)
  }

  const computeMention = (value: string, caret: number) => {
    const before = value.slice(0, caret)
    const m = before.match(/@([^\s@]*)$/)
    if (!m) return { open: false, start: caret, q: "" }
    return { open: true, start: m.index as number, q: m[1] }
  }

  const runMentionSearch = async (q: string) => {
    if (!q) { setMention((p) => ({ ...p, results: [] })); return }
    const hits = await searchMemory(q, 8)
    setMention((p) => ({ ...p, results: hits }))
  }

  const onInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const value = e.target.value
    const caret = e.target.selectionStart ?? value.length
    setInput(value)
    const m = computeMention(value, caret)
    if (m.open) {
      setMention((p) => ({ ...p, open: true, start: m.start, q: m.q, active: 0 }))
      if (mentionTimer.current) window.clearTimeout(mentionTimer.current)
      mentionTimer.current = window.setTimeout(() => runMentionSearch(m.q), 200)
    } else {
      setMention((p) => ({ ...p, open: false, results: [] }))
    }
  }

  const applyMention = (hit: MemorySearchHit) => {
    const ref = `@${hit.key}`
    setInput((prev) => {
      const afterStart = mention.start + 1 + mention.q.length
      return prev.slice(0, mention.start) + ref + prev.slice(afterStart)
    })
    setMention((p) => ({ ...p, open: false, results: [], q: "", start: 0, active: 0 }))
    setTimeout(() => {
      const ta = taRef.current
      if (ta) { ta.focus(); ta.selectionStart = ta.selectionEnd = ta.value.length }
    }, 0)
  }

  const onKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (mention.open && mention.results.length > 0) {
      if (e.key === "ArrowDown") { e.preventDefault(); setMention((p) => ({ ...p, active: (p.active + 1) % p.results.length })); return }
      if (e.key === "ArrowUp") { e.preventDefault(); setMention((p) => ({ ...p, active: (p.active - 1 + p.results.length) % p.results.length })); return }
      if (e.key === "Enter" || e.key === "Tab") { e.preventDefault(); applyMention(mention.results[mention.active]); return }
      if (e.key === "Escape") { e.preventDefault(); setMention((p) => ({ ...p, open: false, results: [] })); return }
    }
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send() }
    if (e.key === "Escape" && isThinking) { e.preventDefault(); stop() }
  }

  // 全局快捷键：j/k 消息浏览 / / 聚焦输入（仅输入框失焦时生效）
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName?.toLowerCase();
      if (tag === "input" || tag === "textarea" || tag === "select") return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "/") { e.preventDefault(); taRef.current?.focus(); }
      else if (e.key === "j") {
        e.preventDefault();
        scrollRef.current?.scrollBy({ top: 120, behavior: "smooth" });
      }
      else if (e.key === "k") {
        e.preventDefault();
        scrollRef.current?.scrollBy({ top: -120, behavior: "smooth" });
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  const copyAll = () => {
    const md = messages.map((m) => `### ${m.role === "user" ? "用户" : "助手"}\n\n${m.content}`).join("\n---\n\n")
    navigator.clipboard?.writeText(md)
  }

  const toggleCanvas = () => {
    const opening = !showCanvas
    setShowCanvas(opening)
    if (opening) {
      // 打开时加载「当前会话」的画布（存档优先，否则由对话内容自动生成），不再回退全局画布
      loadCanvasForSession(currentSessionId, messages)
    }
  }

  // 画布节点保存到 localStorage（按会话隔离）
  const saveCanvasToSession = (data: Partial<CanvasData> & { nodes: any[]; edges: any[] }) => {
    const full: CanvasData = { id: currentSessionId || "main", nodes: data.nodes, edges: data.edges }
    setCanvas(full)
    if (currentSessionId) {
      localStorage.setItem("xai_canvas_" + currentSessionId, JSON.stringify(full))
    }
  }

  // P1: 执行画布节点（SSE 流式）
  const onExecuteCanvasNode = useCallback(async (nodeId: string, nodeData: any) => {
    const token = await getToken()
    const cnvs = canvas || { nodes: [], edges: [] }
    setRunningNodes((p) => { const s = new Set(p); s.add(nodeId); return s })
    try {
      const resp = await fetch(`${apiBase()}/api/canvas/execute`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Auth-Token": token },
        body: JSON.stringify({ nodeId, data: nodeData, session: currentSessionId || "" }),
      })
      const reader = resp.body?.getReader()
      if (!reader) return
      const dec = new TextDecoder()
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        for (const line of dec.decode(value, { stream: true }).split("\n")) {
          if (!line.startsWith("data: ")) continue
          try {
            const ev = JSON.parse(line.slice(6))
            if (ev.type === "status") {
              setCanvas((prev) => {
                if (!prev) return prev
                const nodes = prev.nodes.map((n: any) =>
                  String(n.id) === ev.nodeId ? { ...n, data: { ...n.data, status: ev.status, result: ev.result, tokenUsage: ev.usage, error: ev.error } } : n)
                return { ...prev, nodes }
              })
              if (ev.status === "done" || ev.status === "failed") {
                setRunningNodes((p) => { const s = new Set(p); s.delete(nodeId); return s })
              }
            } else if (ev.type === "log") {
              // 执行日志仅展示在画布节点上（status 颜色变更），不推对话
            }
          } catch {}
        }
      }
    } catch (e: any) {
      setRunningNodes((p) => { const s = new Set(p); s.delete(nodeId); return s })
    }
  }, [canvas, currentSessionId])

  // P1: 画布节点加入对话（上下文注入）
  const onCanvasNodeToChat = useCallback((nodeId: string, nodeData: any) => {
    const ctx = [
      `[画布节点: ${nodeData.label || nodeId}]`,
      `类型: ${nodeData.nodeType || "text"}`, `工具: ${nodeData.tool || "无"}`,
      `状态: ${nodeData.status || "idle"}`,
      nodeData.result ? `结果: ${typeof nodeData.result === "string" ? nodeData.result : JSON.stringify(nodeData.result).slice(0, 200)}` : "",
      nodeData.error ? `错误: ${nodeData.error}` : "",
    ].filter(Boolean).join("\n")
    setInput((prev) => prev + (prev ? "\n\n" : "") + ctx + "\n\n")
  }, [])

  // 由本会话消息自动生成「与该对话相关」的画布（无手动存档时展示，避免所有会话共用同一空/全局画布）
  const buildCanvasFromMessages = (sid: string, msgs: ChatMsg[]): CanvasData => {
    const recent = (msgs || []).slice(-24)
    const nodes = recent.map((m, i) => {
      const isUser = m.role === "user"
      const text = (m.content || "").replace(/\s+/g, " ").trim()
      const snippet = (text || (isUser ? "（用户输入）" : "（生成中）")).slice(0, 46)
      return {
        id: "m_" + m.id,
        type: "default",
        position: { x: isUser ? 24 : 300, y: 16 + i * 60 },
        data: { label: (isUser ? "用户 · " : "助手 · ") + snippet + (text.length > 46 ? "…" : ""), nodeType: isUser ? "user" : "assistant" },
        style: isUser
          ? { background: "var(--color-accent-bg)", border: "1px solid var(--color-accent)", borderRadius: 10, padding: 8, fontSize: 11.5, width: 250, color: "var(--color-accent)" }
          : { background: "var(--color-bg-input)", border: "1px solid var(--color-border-subtle)", borderRadius: 10, padding: 8, fontSize: 11.5, width: 250, color: "var(--color-text)" },
      } as any
    })
    return { id: sid, nodes, edges: [] }
  }

  // 按会话加载画布：优先读该会话本地存档；无存档则自动由对话内容生成；不再回退全局画布
  const loadCanvasForSession = (sid: string | null, msgs: ChatMsg[]) => {
    if (!sid) { setCanvas({ id: "main", nodes: [], edges: [] }); return }
    try {
      const raw = localStorage.getItem("xai_canvas_" + sid)
      if (raw) {
        const d = JSON.parse(raw)
        setCanvas({ id: sid, nodes: d.nodes || [], edges: d.edges || [] })
        return
      }
    } catch {}
    setCanvas(buildCanvasFromMessages(sid, msgs))
  }

  // E1: 从后端加载节点
  const addAgentNodes = async () => {
    try {
      const agents = await fetchAgents()
      const cnvs = canvas || { nodes: [], edges: [] }
      const ns = agents.map((a, i) => ({
        id: "agent_" + a.id,
        type: "default",
        position: { x: 50, y: 20 + i * 80 },
        data: { label: `${a.name}\n${a.role} · ${a.backend}`, nodeType: "agent" },
        style: { background: "#eff6ff", border: "2px solid #3b82f6", borderRadius: 10, padding: 10, fontSize: 12, width: 160, color: "#1e3a5f" } as any,
      }))
      saveCanvasToSession({ nodes: [...cnvs.nodes, ...ns], edges: cnvs.edges })
    } catch {}
  }

  const addCapNodes = async () => {
    try {
      const caps = await fetchCapabilities()
      const cnvs = canvas || { nodes: [], edges: [] }
        const ns = caps.map((c: any, i: number) => ({
          id: "cap_" + (c.id || i),
          type: "default",
          position: { x: 260, y: 20 + i * 80 },
          data: { label: `${c.name || c.id}\n${(c.description || "").slice(0, 40)}`, nodeType: "capability" },
        style: { background: "#ecfdf5", border: "2px solid #10b981", borderRadius: 10, padding: 10, fontSize: 12, width: 180, color: "#064e3b" } as any,
      }))
      saveCanvasToSession({ nodes: [...cnvs.nodes, ...ns], edges: cnvs.edges })
    } catch {}
  }

  // E2: 增强同步
  const syncToCanvas = (content: string) => {
    const cnvs = canvas || { nodes: [], edges: [] }
    let idx = cnvs.nodes.length
    const codeBlocks = content.match(/```(\w*)\n([\s\S]*?)```/g)
    if (codeBlocks) {
      codeBlocks.forEach((cb) => {
        const lang = cb.match(/```(\w*)/)?.[1] || ""
        const code = cb.replace(/```\w*\n?/, "").replace(/```$/, "").trim()
        cnvs.nodes.push({
          id: "sync_code_" + (++idx), type: "default",
          position: { x: 50 + Math.random() * 200, y: cnvs.nodes.length * 70 },
          data: { label: `${lang || "code"}: ${code.slice(0, 60)}...`, nodeType: "code" },
          style: { background: "#1e1e2e", border: "2px solid #a78bfa", borderRadius: 10, padding: 10, fontSize: 11, width: 200, color: "#e2e8f0" } as any,
        })
      })
    }
    const listItems = content.split("\n").filter((l) => /^[\-\d]+[.\)]\s/.test(l.trim()))
    if (listItems.length > 0) {
      cnvs.nodes.push({
        id: "sync_list_" + (++idx), type: "default",
        position: { x: 50 + Math.random() * 200, y: cnvs.nodes.length * 70 },
        data: { label: `要点 (${listItems.length})\n${listItems.slice(0, 3).join("\n")}`, nodeType: "text" },
        style: { background: "#fffbeb", border: "2px solid #f59e0b", borderRadius: 10, padding: 10, fontSize: 11, width: 220, color: "#78350f" } as any,
      })
    }
    if (!codeBlocks && listItems.length === 0 && content.length > 30) {
      cnvs.nodes.push({
        id: "sync_text_" + (++idx), type: "default",
        position: { x: 50 + Math.random() * 200, y: cnvs.nodes.length * 70 },
        data: { label: content.slice(0, 120) + (content.length > 120 ? "..." : ""), nodeType: "text" },
        style: { background: "var(--color-bg-input)", border: "1px solid var(--color-border-subtle)", borderRadius: 10, padding: 10, fontSize: 12, width: 200, color: "var(--color-text)" } as any,
      })
    }
    saveCanvasToSession({ nodes: cnvs.nodes, edges: cnvs.edges })
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", minWidth: 0 }}>
      {/* 头部状态条 */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 16px", borderBottom: "1px solid var(--color-border-subtle)" }}>
        <MessageSquare size={16} style={{ color: "var(--color-accent)" }} />
        <span style={{ fontSize: 15, fontWeight: 700, color: "var(--color-text)" }}>{sessionTitle || "XAI 对话控制台"}</span>
        <span style={{ fontSize: 11, color: "var(--color-text-muted)" }}>
          {status?.engine ? `引擎 ${status.engine}` : "连接中…"}
          {status?.model ? ` · ${status.model}` : ""}
        </span>
        <button onClick={copyAll} disabled={messages.length === 0}
          style={{ marginLeft: "auto", display: "inline-flex", alignItems: "center", gap: 5, padding: "4px 10px", borderRadius: 8, fontSize: 12, cursor: messages.length ? "pointer" : "default", border: "1px solid var(--color-border-subtle)", background: "var(--color-bg-input)", color: "var(--color-text-muted)" }}>
          <Download size={13} /> 导出
        </button>
        <button onClick={toggleCanvas}
          style={{ display: "inline-flex", alignItems: "center", gap: 5, padding: "4px 10px", borderRadius: 8, fontSize: 12, cursor: "pointer", border: "1px solid " + (showCanvas ? "var(--color-accent)" : "var(--color-border-subtle)"), background: showCanvas ? "var(--color-accent-bg)" : "var(--color-bg-input)", color: showCanvas ? "var(--color-accent)" : "var(--color-text-muted)" }}>
          <Network size={13} /> 画布
        </button>
      </div>

      {/* 主内容区：flex row，右侧画布切换 */}
      <div ref={mainAreaRef} style={{ flex: 1, display: "flex", minHeight: 0, overflow: "hidden" }}>
        {/* 消息 + 输入区 */}
        <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0, position: "relative" }}
          onDragOver={handleDragOver} onDrop={handleDrop}>

      {/* 消息区 */}
      <div ref={scrollRef} onScroll={onScroll} style={{ flex: 1, overflowY: "auto", padding: 16, display: "flex", flexDirection: "column", gap: 14, position: "relative" }}>
        {messages.length === 0 && !isThinking && (
          <div style={{ margin: "auto", maxWidth: 380, textAlign: "center", display: "flex", flexDirection: "column", gap: 14 }}>
            <div style={{ padding: "18px 22px", borderRadius: 12, background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}>
              <div style={{ fontSize: 14, fontWeight: 700, color: "var(--color-text)", marginBottom: 4, display: "flex", alignItems: "center", gap: 8, justifyContent: "center" }}>
                <Bot size={18} style={{ color: "var(--color-accent)" }} /> 你好，我是 XAI 统一编排助手
              </div>
              <div style={{ fontSize: 12.5, color: "var(--color-text-muted)", lineHeight: 1.55 }}>直接对话下达任务，或输入斜杠命令。回复由后端实时流式生成。</div>
            </div>
            {EXAMPLES.map((p) => (
              <button key={p} onClick={() => { setInput(p); setTimeout(() => taRef.current?.focus(), 50) }}
                style={{ padding: "10px 14px", borderRadius: 12, cursor: "pointer", textAlign: "left", fontSize: 12.5, color: "var(--color-text)", background: "var(--color-bg-card)", border: "1px solid var(--color-border-subtle)" }}>
                {p}
              </button>
            ))}
          </div>
        )}

        {messages.map((m, i) => (
          <div key={m.id}>
            <MessageRow key={m.id} m={m} isLast={i === messages.length - 1}
              onCopy={() => navigator.clipboard?.writeText(m.content)}
              onRegen={() => { if (m.role === "user") { setInput(m.content); setTimeout(() => taRef.current?.focus(), 50) } }}
              canRegen={!isThinking} />
            {m.role === "assistant" && m.done && m.content && (
              <button onClick={() => syncToCanvas(m.content)}
                className="ml-8 mt-1 flex items-center gap-1 text-[10px] text-purple-500 hover:text-purple-700 px-2 py-0.5 rounded hover:bg-purple-50 dark:hover:bg-purple-950">
                <Network size={10} /> 同步到画布
              </button>
            )}
          </div>
        ))}

        {isThinking && (
          <div style={{ alignSelf: "flex-start", color: "var(--color-text-muted)", display: "flex", gap: 8, alignItems: "center", fontSize: 13 }}>
            <Loader2 size={14} className="animate-spin" /> 思考中…
          </div>
        )}
        <div ref={bottomRef} />
        {showToBottom && (
          <button onClick={() => scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" })}
            style={{ position: "absolute", right: 18, bottom: 14, width: 32, height: 32, borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center", background: "var(--color-bg-elevated)", border: "1px solid var(--color-border-subtle)", color: "var(--color-text)", cursor: "pointer", boxShadow: "0 2px 8px rgba(0,0,0,0.15)" }}>
            <ArrowDown size={15} />
          </button>
        )}
      </div>

      {/* 内核切换 */}
      <div style={{ padding: "6px 16px 0", display: "flex", gap: 6, alignItems: "center" }}>
        {(["hermes", "grok_build", ""] as const).map((k) => {
          const active = kernel === k
          return (
            <button key={k} onClick={() => setKernel(k)}
              style={{ display: "inline-flex", alignItems: "center", gap: 5, padding: "3px 10px", borderRadius: 9, fontSize: 11.5, fontWeight: 600, cursor: "pointer",
                border: active ? "1.5px solid var(--color-accent)" : "1px solid var(--color-border-subtle)",
                background: active ? "var(--color-accent-bg)" : "var(--color-bg-input)",
                color: active ? "var(--color-accent)" : "var(--color-text-muted)" }}>
              {k === "hermes" && <Bot size={12} />}
              {k === "grok_build" && <Cpu size={12} />}
              {KERNEL_LABEL[k]}
            </button>
          )
        })}
      </div>

      {/* 快捷指令 — 顶部固定，悬停高亮 */}
      <div style={{ padding: "4px 16px 6px", display: "flex", gap: 4, overflowX: "auto", whiteSpace: "nowrap", borderTop: "1px solid var(--color-border-subtle)", background: "var(--color-bg-input)", flexShrink: 0 }}>
        {QUICK.map((a) => (
          <button key={a.label} onClick={() => setInput(a.label)} title={a.label}
            style={{ padding: "5px 8px", borderRadius: 8, border: "1px solid var(--color-border-subtle)", background: "transparent", color: "var(--color-text-muted)", cursor: "pointer", lineHeight: 1, flexShrink: 0, transition: "all 0.15s", fontSize: 12, display: "inline-flex", alignItems: "center", gap: 4 }}
            onMouseEnter={e => { e.currentTarget.style.borderColor = "var(--color-accent)"; e.currentTarget.style.color = "var(--color-accent)"; e.currentTarget.style.background = "var(--color-accent-bg)"; }}
            onMouseLeave={e => { e.currentTarget.style.borderColor = "var(--color-border-subtle)"; e.currentTarget.style.color = "var(--color-text-muted)"; e.currentTarget.style.background = "transparent"; }}
          >
            {a.el}
            <span style={{ fontSize: 11 }}>{a.label}</span>
          </button>
        ))}
      </div>

      {/* 输入区 */}
      <div style={{ padding: "4px 16px 16px", display: "flex", flexDirection: "column", gap: 6 }}>
        {err && <div style={{ fontSize: 12, color: "#ef4444", display: "flex", alignItems: "center", gap: 4 }}><AlertCircle size={12} /> {err}</div>}
        {routeHint && (
          <div style={{ fontSize: 11, color: "var(--color-accent)", display: "flex", alignItems: "center", gap: 4, padding: "2px 0" }}>
            <Cpu size={12} /> {routeHint}
          </div>
        )}
        {/* 附件预览 chip */}
        {attachments.length > 0 && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {attachments.map((att) => (
              <div key={att.id} style={{
                display: "flex", alignItems: "center", gap: 4, padding: "4px 8px",
                borderRadius: 8, border: `1px solid ${att.error ? "#ef4444" : "var(--color-border-subtle)"}`,
                background: "var(--color-bg-input)", fontSize: 11,
              }}>
                {att.is_image && att.dataUrl ? (
                  <img src={att.dataUrl} alt={att.name} style={{ width: 22, height: 22, borderRadius: 4, objectFit: "cover" }} />
                ) : att.is_image ? (
                  <ImageIcon size={14} style={{ color: "var(--color-accent)" }} />
                ) : (
                  <FileIcon size={14} style={{ color: "var(--color-text-muted)" }} />
                )}
                <span style={{ maxWidth: 100, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: att.error ? "#ef4444" : "var(--color-text)" }}>
                  {att.name}
                </span>
                {att.uploading && <Loader2 size={10} className="animate-spin" style={{ color: "var(--color-accent)" }} />}
                {att.error && <span style={{ color: "#ef4444", fontSize: 10 }} title={att.error}><AlertCircle size={10} /></span>}
                <button onClick={() => removeAtt(att.id)} style={{ padding: 0, border: "none", background: "none", cursor: "pointer", color: "var(--color-text-muted)", display: "flex" }}>
                  <X size={12} />
                </button>
              </div>
            ))}
          </div>
        )}
        <div style={{ position: "relative" }}>
          {/* 隐藏文件输入 */}
          <input ref={fileInputRef} type="file" multiple onChange={handleFileSelect}
            style={{ display: "none" }}
            accept={fileAccept} />
          {/* 视觉能力提示 */}
          {attachments.some((a) => a.is_image) && (
            <div style={{ fontSize: 11, display: "flex", alignItems: "center", gap: 4, marginBottom: 6, color: props?.activeModelVision ? "var(--color-node-logic)" : "var(--color-text-subtle)" }}>
              <ImageIcon size={12} />
              {props?.activeModelVision
                ? "当前模型支持视觉，图片将作为视觉输入发送给模型"
                : "当前模型不支持视觉，图片仅作为附件记录（模型无法看见图片）"}
            </div>
          )}
          <div style={{ display: "flex", gap: 8 }}>
            {/* + 按钮 → 分类上传菜单 */}
            <div ref={uploadMenuRef} style={{ position: "relative" }}>
              <button onClick={() => setUploadMenuOpen(o => !o)}
                title="上传文件/图片/音频（也可直接粘贴截图或拖拽文件）"
                style={{ padding: "8px 10px", borderRadius: 10, border: "1px solid var(--color-border-subtle)", background: "var(--color-bg-input)", color: "var(--color-text-muted)", cursor: "pointer", display: "inline-flex", alignItems: "center", transition: "color 0.15s" }}
                onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.color = "var(--color-accent)" }}
                onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.color = "var(--color-text-muted)" }}
              >
                <Plus size={18} />
              </button>
              {uploadMenuOpen && (
                <div style={{ position: "absolute", bottom: "calc(100% + 6px)", left: 0, background: "var(--color-bg-elevated)", border: "1px solid var(--color-border-subtle)", borderRadius: 10, boxShadow: "0 8px 24px rgba(0,0,0,0.18)", zIndex: 30, padding: 4, display: "flex", flexDirection: "column", minWidth: 128 }}>
                  <button onClick={() => { setFileAccept("image/*"); setUploadMenuOpen(false); fileInputRef.current?.click() }}
                    style={{ display: "flex", alignItems: "center", gap: 8, padding: "7px 10px", borderRadius: 7, border: "none", background: "transparent", cursor: "pointer", color: "var(--color-text)", fontSize: 12.5, textAlign: "left" }}
                    onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.background = "var(--color-accent-bg)" }}
                    onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.background = "transparent" }}>
                    <ImageIcon size={14} style={{ color: "var(--color-accent)" }} /> 图片
                  </button>
                  <button onClick={() => { setFileAccept("audio/*,video/*,.pdf,.txt,.md,.py,.js,.ts,.json,.csv,.yaml,.yml,.html,.css,.log,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.zip"); setUploadMenuOpen(false); fileInputRef.current?.click() }}
                    style={{ display: "flex", alignItems: "center", gap: 8, padding: "7px 10px", borderRadius: 7, border: "none", background: "transparent", cursor: "pointer", color: "var(--color-text)", fontSize: 12.5, textAlign: "left" }}
                    onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.background = "var(--color-accent-bg)" }}
                    onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.background = "transparent" }}>
                    <FileIcon size={14} style={{ color: "var(--color-text-muted)" }} /> 文件
                  </button>
                </div>
              )}
            </div>
            <textarea ref={taRef} value={input} onChange={onInputChange} onKeyDown={onKey} onPaste={handlePaste}
              placeholder="输入问题或斜杠命令，输入 @ 引用记忆（Enter 发送，Shift+Enter 换行，Esc 中断）"
              style={{ flex: 1, padding: "10px 12px", borderRadius: 10, border: "1px solid var(--color-border-subtle)", background: "var(--color-bg-input)", color: "var(--color-text)", fontSize: 14, outline: "none", resize: "none", fontFamily: "inherit", lineHeight: 1.5, overflow: "auto" }} />
            {isThinking ? (
              <button onClick={stop} style={{ padding: "8px 16px", borderRadius: 10, border: "1px solid var(--color-border-subtle)", background: "var(--color-bg-hover)", color: "var(--color-text)", cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 5 }}>
                <Loader2 size={14} className="animate-spin" /> 停止
              </button>
            ) : (
              <button onClick={send} disabled={!input.trim() && attachments.length === 0} style={{ padding: "8px 16px", borderRadius: 10, border: "none", background: (input.trim() || attachments.length > 0) ? "var(--color-accent)" : "var(--color-bg-hover)", color: "#fff", cursor: (input.trim() || attachments.length > 0) ? "pointer" : "default", display: "inline-flex", alignItems: "center", gap: 5, transition: "all 0.15s ease" }}
                onMouseDown={(e) => { const btn = e.currentTarget; btn.style.transform = "scale(0.93)"; }}
                onMouseUp={(e) => { const btn = e.currentTarget; btn.style.transform = "scale(1)"; }}
                onMouseLeave={(e) => { const btn = e.currentTarget; btn.style.transform = "scale(1)"; }}
              >
                <Send size={16} /> 发送
              </button>
            )}
          </div>
          {mention.open && mention.results.length > 0 && (
            <div style={{ position: "absolute", bottom: "calc(100% + 6px)", left: 0, right: 0, maxHeight: 224, overflowY: "auto", background: "var(--color-bg-elevated)", border: "1px solid var(--color-border-subtle)", borderRadius: 10, boxShadow: "0 8px 24px rgba(0,0,0,0.18)", zIndex: 30, padding: 4 }}>
              <div style={{ fontSize: 10.5, color: "var(--color-text-subtle)", padding: "4px 8px 2px" }}>引用记忆（↑↓ 选择 · Enter 确认 · Esc 关闭）</div>
              {mention.results.map((h, i) => (
                <button key={h.key + "_" + i} onMouseDown={(e) => { e.preventDefault(); applyMention(h) }} onMouseEnter={() => setMention((p) => ({ ...p, active: i }))}
                  style={{ display: "block", width: "100%", textAlign: "left", padding: "7px 8px", borderRadius: 7, background: i === mention.active ? "var(--color-accent-bg)" : "transparent", border: "none", cursor: "pointer", color: "var(--color-text)" }}>
                  <div style={{ fontSize: 12.5, fontWeight: 600, color: "var(--color-accent)" }}>@{h.key}</div>
                  <div style={{ fontSize: 11, color: "var(--color-text-muted)", marginTop: 1, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{mentionPreview(h.value)}</div>
                  <div style={{ fontSize: 10, color: "var(--color-text-subtle)", marginTop: 1 }}>{h.layer} · 相关度 {h.score}</div>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

        </div>{/* close messages+input wrapper */}

        {/* 可拖拽分隔条 */}
        {showCanvas && (
          <div
            onMouseDown={(e) => { draggingRef.current = true; document.body.style.cursor = "col-resize"; document.body.style.userSelect = "none" }}
            style={{ width: 6, flexShrink: 0, cursor: "col-resize", background: "transparent", position: "relative" }}
            title="拖拽调整画布占比"
          >
            <div style={{ position: "absolute", left: 2, top: 0, bottom: 0, width: 2, background: "var(--color-border-subtle)" }} />
          </div>
        )}

        {/* 右侧画布 */}
        {showCanvas && (
          <div style={{ width: `${canvasWidth}%`, minWidth: 280, maxWidth: 800, borderLeft: "1px solid var(--color-border-subtle)", background: "var(--color-bg-card)", display: "flex", flexDirection: "column" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 12px", borderBottom: "1px solid var(--color-border-subtle)" }}>
              <Network size={13} style={{ color: "var(--color-accent)" }} />
              <span style={{ fontSize: 12, fontWeight: 600, color: "var(--color-text)" }}>画布</span>
              <span style={{ fontSize: 10, color: "var(--color-text-muted)", fontFamily: "monospace" }}>{canvasWidth.toFixed(0)}%</span>
              <span style={{ fontSize: 10, color: "var(--color-text-muted)" }}>· {canvas?.nodes?.length || 0} 节点</span>
              {/* 快捷操作按钮 */}
              <button onClick={addAgentNodes} title="加载Agent节点"
                className="px-2 py-0.5 rounded text-[10px] bg-blue-50 dark:bg-blue-950 text-blue-600 dark:text-blue-400 hover:bg-blue-100">
                +Agent
              </button>
              <button onClick={addCapNodes} title="加载能力节点"
                className="px-2 py-0.5 rounded text-[10px] bg-emerald-50 dark:bg-emerald-950 text-emerald-600 dark:text-emerald-400 hover:bg-emerald-100">
                +能力
              </button>
              <button onClick={() => {
                const cnvs = canvas || { nodes: [], edges: [] }
                const n: any = { id: "n" + Date.now(), type: "default", position: { x: 50 + Math.random() * 200, y: 20 + cnvs.nodes.length * 70 }, data: { label: "新节点 " + (cnvs.nodes.length + 1), nodeType: "text" }, style: { background: "var(--color-bg-input)", border: "1px solid var(--color-border-subtle)", borderRadius: 8, padding: 8, fontSize: 12, width: 140, color: "var(--color-text)" } }
                saveCanvasToSession({ nodes: [...cnvs.nodes, n], edges: cnvs.edges })
              }} title="添加节点"
                className="px-2 py-0.5 rounded text-[10px] bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300 hover:bg-zinc-200">
                +节点
              </button>
              <button onClick={() => saveCanvasToSession({ nodes: [], edges: [] })} title="清空画布"
                className="px-2 py-0.5 rounded text-[10px] text-zinc-400 hover:text-red-500">
                清空
              </button>
              <button onClick={() => setShowPalette((v) => !v)} title="节点库（拖拽加载 MCP/Skill/工具节点）"
                className="px-2 py-0.5 rounded text-[10px] bg-violet-50 dark:bg-violet-950 text-violet-600 dark:text-violet-400 hover:bg-violet-100">
                {showPalette ? "关闭节点库" : "节点库"}
              </button>
              <button onClick={() => setCanvasViewMode((m) => m === "dag" ? "kanban" : "dag")} title="切换 DAG / 看板视图"
                className="px-2 py-0.5 rounded text-[10px] bg-amber-50 dark:bg-amber-950 text-amber-600 dark:text-amber-400 hover:bg-amber-100">
                {canvasViewMode === "dag" ? "📋 看板" : "🔗 DAG"}
              </button>
              <button onClick={toggleCanvas} title="收起画布"
                style={{ marginLeft: "auto", padding: "2px 8px", borderRadius: 6, fontSize: 11, background: "var(--color-bg-input)", border: "1px solid var(--color-border-subtle)", color: "var(--color-text-muted)", cursor: "pointer" }}>
                收起
              </button>
            </div>
            <div style={{ flex: 1, position: "relative", display: "flex", gap: 6, padding: showPalette ? 6 : 0 }}>
              {showPalette && <NodePalette />}
              <div style={{ flex: 1, position: "relative", minWidth: 0 }}>
                {canvas ? (
                  <>
                    <MiniCanvas nodes={canvas.nodes} edges={canvas.edges} onPersist={saveCanvasToSession}
                      viewMode={canvasViewMode} onViewModeChange={setCanvasViewMode}
                      onExecuteNode={onExecuteCanvasNode} onAddToChat={onCanvasNodeToChat}
                      runningNodes={runningNodes} />
                    {canvas.nodes.length === 0 && (
                      <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, color: "var(--color-text-muted)", pointerEvents: "none" }}>
                        画布为空 — 点「节点库」拖入节点，或 AI 回复后「同步到画布」
                      </div>
                    )}
                  </>
                ) : (
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", fontSize: 12, color: "var(--color-text-muted)" }}>加载画布…</div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>{/* close main flex row */}
    </div>
  )
}

/* ---------- 单条消息 ---------- */
function MessageRow({ m, isLast, onCopy, onRegen, canRegen }: {
  m: ChatMsg; isLast: boolean; onCopy: () => void; onRegen: () => void; canRegen: boolean
}) {
  const isUser = m.role === "user"
  const bubble = isUser
    ? { background: "var(--color-accent)", border: "none", color: "#fff" }
    : { background: "var(--color-bg-input)", border: "1px solid var(--color-border-subtle)", color: "var(--color-text)" }
  return (
    <div style={{ alignSelf: isUser ? "flex-end" : "flex-start", maxWidth: "82%", display: "flex", flexDirection: "column", gap: 4 }}>
      {!isUser && !m.done && m.events.length > 0 && (
        <ProgressIndicator progress={buildProgressInfo(m.events)} />
      )}
      {!isUser && (m.thinking.length > 0 || m.intent || m.guard || m.plan.length > 0) && (
        <ThinkingPanel m={m} />
      )}
      <div style={{ display: "flex", gap: 8, alignItems: "flex-end" }}>
        {!isUser && <div style={{ width: 24, height: 24, borderRadius: 7, background: "var(--color-accent-bg)", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--color-accent)", flexShrink: 0, marginBottom: 2 }}><Bot size={14} /></div>}
        <div style={{ padding: "10px 14px", borderRadius: 10, ...bubble, fontSize: 14, lineHeight: 1.55, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
          {isUser ? (m.content || "") : (m.content ? <MessageContent content={m.content} /> : "…")}
        </div>
      </div>
      {!isUser && m.content && (
        <div style={{ display: "flex", gap: 4, marginTop: 2, alignItems: "center", paddingLeft: 32 }}>
          <IconAct icon={<Copy size={13} />} title="复制" onClick={onCopy} />
          {isLast && <IconAct icon={<RefreshCw size={13} />} title="重新生成" onClick={onRegen} disabled={!canRegen} />}
          {m.kernel && <span style={{ fontSize: 10.5, color: "var(--color-text-subtle)", marginLeft: 4 }}>{KERNEL_LABEL[m.kernel] || m.kernel}</span>}
          {m.usage && (
            <span style={{ fontSize: 10.5, color: "var(--color-text-subtle)", marginLeft: 4 }}>
              ↑{(m.usage.prompt_tokens / 1000).toFixed(1)}k ↓{(m.usage.completion_tokens / 1000).toFixed(1)}k tokens
            </span>
          )}
        </div>
      )}
    </div>
  )
}

function IconAct({ icon, title, onClick, disabled }: any) {
  return (
    <button title={title} onClick={onClick} disabled={disabled}
      style={{ width: 26, height: 26, borderRadius: 7, display: "flex", alignItems: "center", justifyContent: "center", background: "transparent", border: "1px solid var(--color-border-subtle)", color: "var(--color-text-subtle)", cursor: disabled ? "default" : "pointer", opacity: disabled ? 0.4 : 1 }}>
      {icon}
    </button>
  )
}

/* ---------- 思考过程可视化 ---------- */
function ThinkingPanel({ m }: { m: ChatMsg }) {
  const [open, setOpen] = useState(false)
  const levelColor = m.guard?.level === "P0" ? "#ef4444" : m.guard?.level === "P1" ? "#f59e0b" : "#10b981"
  const hasContent = !!m.intent || !!m.guard || m.plan.length > 0 || m.thinking.length > 0
  if (!hasContent) return null
  return (
    <div style={{ border: "1px solid var(--color-border-subtle)", borderRadius: 9, background: "var(--color-bg-input)", fontSize: 12, overflow: "hidden", marginTop: 2 }}>
      <button onClick={() => setOpen((v) => !v)} style={{ display: "flex", alignItems: "center", gap: 6, width: "100%", padding: "6px 10px", background: "transparent", border: "none", color: "var(--color-text-muted)", cursor: "pointer", fontSize: 12 }}>
        {open ? <ChevronUp size={14} style={{ color: "var(--color-text-subtle)" }} /> : <ChevronDown size={14} style={{ color: "var(--color-text-subtle)" }} />}
        <Activity size={13} style={{ color: "var(--color-accent)" }} />
        <span style={{ fontWeight: 600, color: "var(--color-text)" }}>思考过程</span>
        {m.intent && <span style={{ color: "var(--color-accent)" }}>· {m.intent.label}</span>}
        {m.kernel && <span style={{ color: "var(--color-text-muted)", fontSize: 10.5 }}>· {KERNEL_LABEL[m.kernel]}</span>}
        {m.guard && <span style={{ color: levelColor, fontSize: 10.5 }}>● {m.guard.level}</span>}
      </button>
      {open && (
        <div style={{ padding: "8px 12px 10px", display: "flex", flexDirection: "column", gap: 7, borderTop: "1px solid var(--color-border-subtle)" }}>
          {m.intent && (
            <Row icon={<Target size={13} style={{ color: "var(--color-accent)" }} />}
              label={`意图：${m.intent.label} (${(m.intent.conf * 100).toFixed(0)}%)`} sub={m.intent.rationale} />
          )}
          {m.guard && (
            <Row icon={<ShieldCheck size={13} style={{ color: levelColor }} />}
              label={`风险审计：${m.guard.level}`} sub={m.guard.reason} />
          )}
          {m.plan.length > 0 && (
            <div style={{ fontSize: 11.5, color: "var(--color-text-muted)" }}>
              规划 {m.plan.length} 步：
              {m.plan.map((p) => (
                <div key={p.step_id} style={{ paddingLeft: 8, color: "var(--color-text)" }}>· {p.agent}：{p.task}</div>
              ))}
            </div>
          )}
          {m.thinking.map((s, i) => (
            <Row key={i} icon={<Cpu size={12} style={{ color: "var(--color-text-subtle)" }} />}
              label={`${s.stage}`} sub={s.text} />
          ))}
        </div>
      )}
    </div>
  )
}

function Row({ icon, label, sub }: { icon: any; label: string; sub?: string }) {
  return (
    <div style={{ display: "flex", gap: 7, alignItems: "flex-start" }}>
      <span style={{ marginTop: 1, flexShrink: 0, color: "var(--color-text-muted)" }}>{icon}</span>
      <div>
        <div style={{ color: "var(--color-text)" }}>{label}</div>
        {sub && <div style={{ color: "var(--color-text-subtle)", fontSize: 11, marginTop: 1 }}>{sub}</div>}
      </div>
    </div>
  )
}

