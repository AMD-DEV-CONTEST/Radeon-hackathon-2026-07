import { useState, useRef, useEffect, useCallback } from 'react'
import { useLocation } from 'react-router-dom'
import { AlertTriangle, CheckCircle2, GripHorizontal, MessageCircleQuestion, XCircle } from 'lucide-react'
import {
  collectClientDiagnostics,
  installErrorCollector,
  reconcileDiagnoseForBrowser,
} from '../../lib/copilotDiagnostics'
import {
  copilotDiagnose,
  copilotChat,
  type DiagnoseResponse,
  type ChatResponse,
  type PlaybookMatch,
  type SafeDiagnosticSummary,
} from '../../lib/copilotApi'
import { isLocalDev } from '../../lib/localAgent'
import {
  dismissActiveGuides,
  type CopilotAction,
  type CopilotOpenDetail,
} from '../../lib/copilotAgent'
import {
  filterPlaybooksForContext,
  playbookAudienceLabel,
  PLAYBOOK_AUDIENCE,
} from '../../lib/copilotPlaybookMeta'
import { CopilotActionBar } from './CopilotActionBar'
import { ChatMarkdown } from './ChatMarkdown'
import { useDraggablePanel } from './useDraggablePanel'

interface Message {
  role: 'user' | 'assistant'
  content: string
  actions?: CopilotAction[]
}

const SEVERITY_ICON: Record<string, string> = {
  error: '❌',
  warning: '⚠️',
  info: 'ℹ️',
}

const HIGH_RISK_PAGES = ['/setup', '/robots', '/training', '/teleop']
const POLL_INTERVAL_MS = 30_000

export function CopilotWidget() {
  const [open, setOpen] = useState(false)
  const [tab, setTab] = useState<'diagnose' | 'chat'>('chat')
  const [diagError, setDiagError] = useState<string | null>(null)
  const [diagResult, setDiagResult] = useState<DiagnoseResponse | null>(null)
  const [diagLoading, setDiagLoading] = useState(false)
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [chatLoading, setChatLoading] = useState(false)
  const [issueBadge, setIssueBadge] = useState(0)
  const scrollRef = useRef<HTMLDivElement>(null)
  const lastIssueCount = useRef(0)
  const location = useLocation()
  const { pos, onDragStart, onDragMove, onDragEnd, resetPos } = useDraggablePanel(open)

  useEffect(() => {
    installErrorCollector()
  }, [])

  useEffect(() => {
    const onCopilotEvent = (e: Event) => {
      const detail = (e as CustomEvent<CopilotOpenDetail>).detail ?? {}
      if (detail.open !== false) {
        dismissActiveGuides()
        setOpen(true)
        setTab(detail.tab ?? 'chat')
      } else if (detail.tab) {
        setTab(detail.tab)
      }
      if (detail.prefill) setInput(detail.prefill)
    }
    window.addEventListener('botversex:copilot', onCopilotEvent)
    return () => window.removeEventListener('botversex:copilot', onCopilotEvent)
  }, [])

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages])

  const runDiagnose = useCallback(async (silent = false) => {
    if (!silent) setDiagLoading(true)
    try {
      const cd = await collectClientDiagnostics()
      const raw = await copilotDiagnose(location.pathname, cd)
      const result = await reconcileDiagnoseForBrowser(raw)
      setDiagResult(result)
      setDiagError(null)

      const issueCount =
        (result.matches?.length || 0) + (result.server.issues?.length || 0)

      if (!open && issueCount > 0 && issueCount > lastIssueCount.current) {
        setIssueBadge(issueCount)
      }
      lastIssueCount.current = issueCount
    } catch (e) {
      const msg = e instanceof Error ? e.message : '诊断失败'
      setDiagError(msg)
      if (!silent) setDiagResult(null)
    } finally {
      if (!silent) setDiagLoading(false)
    }
  }, [location.pathname, open])

  useEffect(() => {
    if (open && tab === 'diagnose') {
      runDiagnose()
      setIssueBadge(0)
    }
  }, [open, tab, runDiagnose])

  useEffect(() => {
    const isHighRisk = HIGH_RISK_PAGES.some((p) => location.pathname.includes(p))
    if (!isHighRisk) return

    runDiagnose(true)
    const id = setInterval(() => runDiagnose(true), POLL_INTERVAL_MS)
    return () => clearInterval(id)
  }, [location.pathname, runDiagnose])

  const sendMessage = async () => {
    const text = input.trim()
    if (!text || chatLoading) return
    setInput('')
    const userMsg: Message = { role: 'user', content: text }
    setMessages((prev) => [...prev, userMsg])
    setChatLoading(true)
    try {
      const cd = await collectClientDiagnostics()
      const history = [...messages, userMsg].map((m) => ({
        role: m.role,
        content: m.content,
      }))
      const resp: ChatResponse = await copilotChat(
        text,
        location.pathname,
        cd,
        history,
      )
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: resp.answer, actions: resp.actions },
      ])
      if (resp.matches && resp.safe_summary) {
        setDiagResult((prev) =>
          prev
            ? { ...prev, matches: resp.matches!, safe_summary: resp.safe_summary! }
            : prev,
        )
      }
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: `抱歉，出了点问题: ${String(err)}`,
        },
      ])
    } finally {
      setChatLoading(false)
    }
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => {
          dismissActiveGuides()
          setOpen(true)
        }}
        data-tour="copilot-fab"
        className="fixed bottom-5 right-5 z-[10100] flex items-center gap-2 pl-3 pr-4 py-3 rounded-full
          bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]
          shadow-lg shadow-[hsl(var(--primary))]/30 hover:shadow-xl
          transition-all hover:scale-[1.03] active:scale-95"
        title="不懂就问 — BotverseX 助手"
      >
        {issueBadge > 0 && (
          <span className="absolute -top-1 -right-1 min-w-[20px] h-5 px-1 rounded-full
            bg-red-500 text-white text-[10px] font-bold flex items-center justify-center">
            {issueBadge > 9 ? '9+' : issueBadge}
          </span>
        )}
        <MessageCircleQuestion className="h-6 w-6 shrink-0" strokeWidth={2.25} />
        <span className="text-sm font-semibold whitespace-nowrap">智能助手</span>
      </button>
    )
  }

  return (
    <div
      className="copilot-panel fixed z-[10100] w-[380px] max-h-[560px] flex flex-col
      rounded-xl border border-[hsl(var(--border))]
      bg-[hsl(var(--background))] shadow-2xl overflow-hidden"
      style={{ left: pos.x, top: pos.y }}
    >

      <div
        className="flex items-center justify-between px-3 py-2.5
        bg-gradient-to-r from-[hsl(var(--primary))]/10 to-transparent
        border-b border-[hsl(var(--border))]/50 cursor-grab active:cursor-grabbing select-none"
        onPointerDown={onDragStart}
        onPointerMove={onDragMove}
        onPointerUp={onDragEnd}
        onPointerCancel={onDragEnd}
        onDoubleClick={resetPos}
        title="拖动标题栏移动 · 双击复位"
      >
        <div className="flex items-center gap-2 min-w-0">
          <GripHorizontal className="h-4 w-4 shrink-0 text-[hsl(var(--muted-foreground))]" />
          <MessageCircleQuestion className="h-4 w-4 text-[hsl(var(--primary))] shrink-0" />
          <span className="font-semibold text-sm truncate">智能助手 · Agent</span>
        </div>
        <button
          type="button"
          onClick={() => setOpen(false)}
          onPointerDown={(e) => e.stopPropagation()}
          className="text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] transition-colors p-1"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M18 6 6 18" /><path d="m6 6 12 12" />
          </svg>
        </button>
      </div>

      <div className="flex border-b border-[hsl(var(--border))]/50 text-sm">
        <button
          onClick={() => setTab('chat')}
          className={`flex-1 py-2 text-center transition-colors ${
            tab === 'chat'
              ? 'border-b-2 border-[hsl(var(--primary))] text-[hsl(var(--primary))] font-medium'
              : 'text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]'
          }`}
        >
          智能助手
        </button>
        <button
          onClick={() => setTab('diagnose')}
          className={`flex-1 py-2 text-center transition-colors ${
            tab === 'diagnose'
              ? 'border-b-2 border-[hsl(var(--primary))] text-[hsl(var(--primary))] font-medium'
              : 'text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]'
          }`}
        >
          系统诊断
        </button>
      </div>

      <div className="flex-1 overflow-auto min-h-0" ref={scrollRef}>
        {tab === 'diagnose' ? (
          <DiagnosePanel
            result={diagResult}
            error={diagError}
            loading={diagLoading}
            onRetry={() => runDiagnose()}
          />
        ) : (
          <ChatPanel
            messages={messages}
            loading={chatLoading}
            llmEnabled={diagResult?.server.llm_enabled ?? false}
            safeSummary={diagResult?.safe_summary}
            onSuggestion={setInput}
          />
        )}
      </div>

      {tab === 'chat' && (
        <div className="border-t border-[hsl(var(--border))]/50 p-3 flex gap-2">
          <input
            className="flex-1 rounded-lg border border-[hsl(var(--border))] bg-transparent px-3 py-2 text-sm
              focus:outline-none focus:ring-2 focus:ring-[hsl(var(--primary))]/40
              placeholder:text-[hsl(var(--muted-foreground))]/60"
            placeholder="描述你的问题…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                sendMessage()
              }
            }}
            disabled={chatLoading}
          />
          <button
            onClick={sendMessage}
            disabled={chatLoading || !input.trim()}
            className="rounded-lg bg-[hsl(var(--primary))] px-3 py-2 text-sm text-[hsl(var(--primary-foreground))]
              hover:opacity-90 disabled:opacity-40 transition-colors"
          >
            发送
          </button>
        </div>
      )}
    </div>
  )
}

function DiagnosePanel({
  result,
  error,
  loading,
  onRetry,
}: {
  result: DiagnoseResponse | null
  error: string | null
  loading: boolean
  onRetry: () => void
}) {
  if (loading) {
    return (
      <div className="p-6 flex flex-col items-center gap-3 text-sm text-[hsl(var(--muted-foreground))]">
        <div className="w-6 h-6 border-2 border-[hsl(var(--primary))] border-t-transparent rounded-full animate-spin" />
        正在检测系统状态…
      </div>
    )
  }

  if (!result) {
    return (
      <div className="p-6 text-center text-sm space-y-2">
        <p className="text-[hsl(var(--muted-foreground))]">
          {error ?? '无法连接到诊断服务'}
        </p>
        <button onClick={onRetry} className="text-[hsl(var(--primary))] hover:underline text-sm">
          重试
        </button>
      </div>
    )
  }

  const { server, client, matches: rawMatches = [] } = result
  const matches = filterPlaybooksForContext(rawMatches, isLocalDev())
  const issues = server.issues || []
  const overall = server.overall

  return (
    <div className="p-4 space-y-4 text-sm">
      <div className={`flex items-center gap-2 p-3 rounded-lg ${
        overall === 'ok'
          ? 'bg-emerald-500/10 text-emerald-600'
          : overall === 'warning'
          ? 'bg-amber-500/10 text-amber-600'
          : 'bg-red-500/10 text-red-600'
      }`}>
        {overall === 'ok' ? (
          <CheckCircle2 className="h-5 w-5 shrink-0 text-emerald-500" />
        ) : overall === 'warning' ? (
          <AlertTriangle className="h-5 w-5 shrink-0 text-amber-500" />
        ) : (
          <XCircle className="h-5 w-5 shrink-0 text-red-500" />
        )}
        <span className="font-medium">
          {overall === 'ok'
            ? '系统一切正常'
            : overall === 'warning'
            ? '部分功能可能受影响'
            : '发现阻断性问题'}
        </span>
      </div>

      {matches.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-medium text-[hsl(var(--muted-foreground))] uppercase tracking-wide">
            知识库匹配
          </p>
          {matches.map((m) => (
            <PlaybookCard key={m.code} match={m} />
          ))}
        </div>
      )}

      {issues.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-medium text-[hsl(var(--muted-foreground))] uppercase tracking-wide">
            实时检测
          </p>
          {issues.map((iss, i) => (
            <div
              key={i}
              className="p-3 rounded-lg border border-[hsl(var(--border))]/50 bg-[hsl(var(--muted))]/30"
            >
              <div className="flex items-start gap-2">
                <span>{SEVERITY_ICON[iss.severity] || '?'}</span>
                <div>
                  <p className="font-medium">{iss.title}</p>
                  <p className="text-[hsl(var(--muted-foreground))] mt-0.5 text-xs leading-relaxed whitespace-pre-wrap">
                    {iss.message}
                  </p>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="space-y-1.5">
        <CheckRow label="Cloud API" ok={server.cloud_api?.ok} />
        <CheckRow label="Database" ok={server.database?.ok} />
        <CheckRow label="Local Agent / Realtime" ok={server.realtime?.ok} />
        <CheckRow label="Robot manifests" ok={server.robots?.ok} />
        {client?.localAgent && (
          <CheckRow label="Browser→Local Agent" ok={client.localAgent.ok} />
        )}
      </div>

      {result.actions && result.actions.length > 0 && (
        <div>
          <p className="text-xs font-medium text-[hsl(var(--muted-foreground))] uppercase tracking-wide mb-2">
            智能助手可执行
          </p>
          <CopilotActionBar actions={result.actions} />
        </div>
      )}

      <button
        onClick={onRetry}
        className="w-full text-center text-xs text-[hsl(var(--primary))] hover:underline py-1"
      >
        重新检测
      </button>
    </div>
  )
}

function PlaybookCard({ match }: { match: PlaybookMatch }) {
  const audiences = match.audience ?? PLAYBOOK_AUDIENCE[match.code] ?? ['customer']
  const audienceLabel = playbookAudienceLabel(audiences as Array<'customer' | 'developer' | 'cloud'>)

  return (
    <div className="p-3 rounded-lg border border-[hsl(var(--primary))]/30 bg-[hsl(var(--primary))]/5">
      <div className="flex items-start gap-2">
        <span>{SEVERITY_ICON[match.severity] || '?'}</span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <p className="font-medium text-sm">{match.title}</p>
            <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-[hsl(var(--muted))] text-[hsl(var(--muted-foreground))]">
              {audienceLabel}
            </span>
          </div>
        </div>
      </div>
      <p className="text-xs text-[hsl(var(--muted-foreground))] mt-1">{match.root_cause}</p>
      {match.fix_steps?.length > 0 && (
        <ol className="mt-2 space-y-1 text-xs list-decimal list-inside">
          {match.fix_steps.map((step, i) => (
            <li key={i} className="text-[hsl(var(--foreground))]/90">{step}</li>
          ))}
        </ol>
      )}
      {match.verify_steps?.length > 0 && (
        <div className="mt-2 pt-2 border-t border-[hsl(var(--border))]/30">
          <p className="text-[10px] text-[hsl(var(--muted-foreground))] mb-1">验证方式</p>
          <ul className="space-y-0.5">
            {match.verify_steps.map((step, i) => (
              <li key={i} className="text-[10px] text-emerald-600">✓ {step}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

function CheckRow({ label, ok }: { label: string; ok?: boolean }) {
  return (
    <div className="flex items-center justify-between px-1 py-0.5 text-xs">
      <span className="text-[hsl(var(--muted-foreground))]">{label}</span>
      <span>
        {ok == null ? (
          '—'
        ) : ok ? (
          <CheckCircle2 className="inline h-3.5 w-3.5 text-emerald-500" />
        ) : (
          <XCircle className="inline h-3.5 w-3.5 text-red-500" />
        )}
      </span>
    </div>
  )
}

function DiagnosticPreview({ summary }: { summary: SafeDiagnosticSummary }) {
  return (
    <div className="mx-3 mt-3 p-2.5 rounded-lg border border-[hsl(var(--border))]/50 bg-[hsl(var(--muted))]/20 text-[10px] space-y-1">
      <p className="font-medium text-[hsl(var(--foreground))]">发送给 AI 的诊断信息</p>
      <p className="text-[hsl(var(--muted-foreground))]">页面: {summary.page || '—'}</p>
      <p className="text-[hsl(var(--muted-foreground))]">
        检查: Cloud={summary.checks.cloud_api ? '✓' : '✗'} · DB={summary.checks.database ? '✓' : '✗'} · Agent={summary.checks.realtime ? '✓' : '✗'}
      </p>
      {summary.issue_codes.length > 0 && (
        <p className="text-[hsl(var(--muted-foreground))]">问题: {summary.issue_codes.join(', ')}</p>
      )}
      {summary.client && (
        <p className="text-[hsl(var(--muted-foreground))]">
          浏览器: Agent={summary.client.local_agent_ok ? '✓' : '✗'} · 错误数={summary.client.recent_error_count}
        </p>
      )}
    </div>
  )
}

function ChatPanel({
  messages,
  loading,
  llmEnabled,
  safeSummary,
  onSuggestion,
}: {
  messages: Message[]
  loading: boolean
  llmEnabled: boolean
  safeSummary?: SafeDiagnosticSummary
  onSuggestion?: (text: string) => void
}) {
  if (messages.length === 0 && !loading) {
    return (
      <div className="text-sm text-[hsl(var(--muted-foreground))]">
        {safeSummary && <DiagnosticPreview summary={safeSummary} />}
        <div className="p-6 text-center space-y-3">
          <p className="text-base">⚡</p>
          <p>我是 Agent，不只是聊天 — 能诊断、导航、代你操作</p>
          <div className="space-y-1 text-xs">
            <p className="font-medium text-[hsl(var(--foreground))]">试试问：</p>
            <SuggestionChips onSelect={onSuggestion} />
          </div>
          {!llmEnabled && (
            <p className="text-xs text-amber-500 mt-2">
              AI 模型未配置，将使用 Playbook 规则诊断
            </p>
          )}
        </div>
      </div>
    )
  }

  return (
    <div>
      {safeSummary && messages.length > 0 && <DiagnosticPreview summary={safeSummary} />}
      <div className="p-3 space-y-3">
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${
                msg.role === 'user'
                  ? 'bg-[hsl(var(--primary))] text-white whitespace-pre-wrap'
                  : 'bg-[hsl(var(--muted))]/50 border border-[hsl(var(--border))]/50'
              }`}
            >
              {msg.role === 'user' ? msg.content : <ChatMarkdown content={msg.content} />}
              {msg.role === 'assistant' && msg.actions && msg.actions.length > 0 && (
                <CopilotActionBar actions={msg.actions} compact />
              )}
            </div>
          </div>
        ))}
        {loading && (
          <div className="flex justify-start">
            <div className="bg-[hsl(var(--muted))]/50 border border-[hsl(var(--border))]/50 rounded-lg px-3 py-2">
              <div className="flex gap-1">
                <span className="text-xs text-[hsl(var(--muted-foreground))]">正在思考…</span>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function SuggestionChips({ onSelect }: { onSelect?: (text: string) => void }) {
  const path = window.location.pathname
  let suggestions: string[]

  if (path.includes('/setup')) {
    suggestions = [
      '装完 Agent 下一步干嘛？',
      'Setup 和进入向导有什么区别？',
      '复制命令要在哪里运行？',
      'pip install 太慢了怎么办？',
    ]
  } else if (path.includes('/robots')) {
    suggestions = [
      '进入向导之前要做什么？',
      '没有机械臂能玩吗？',
      'Local Agent 怎么启动？',
      '为什么连不上机器人？',
    ]
  } else if (path.includes('/training')) {
    suggestions = [
      '训练任务失败了怎么办？',
      '需要登录吗？',
      '训练特别慢怎么调？',
      'GPU/ROCm 没识别',
    ]
  } else {
    suggestions = [
      '为什么连不上机器人？',
      'Local Agent 怎么启动？',
      '训练任务失败了怎么办？',
      '摄像头检测不到',
    ]
  }

  return (
    <div className="flex flex-wrap gap-1.5 justify-center mt-1">
      {suggestions.map((s, i) => (
        <button
          key={i}
          onClick={() => onSelect?.(s)}
          className="inline-block px-2 py-1 rounded-full text-xs
            border border-[hsl(var(--border))] text-[hsl(var(--muted-foreground))]
            hover:border-[hsl(var(--primary))]/40 hover:text-[hsl(var(--primary))] transition-colors cursor-pointer"
        >
          {s}
        </button>
      ))}
    </div>
  )
}
