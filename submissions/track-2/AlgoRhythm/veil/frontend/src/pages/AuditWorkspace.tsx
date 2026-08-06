import { useState, useCallback, useRef, useEffect } from 'react'
import { useApp } from '@/context/AppContext'
import { openAuditSocket } from '@/lib/ws'
import { api } from '@/lib/api'
import type {
  WsEvent, Finding, PersonaState, IterationState, RunMetrics,
  CurvePoint, RiskBand, EditType,
} from '@/types'
import { PERSONAS, can } from '@/types'
import { cn, formatUtility, formatElapsed, riskToPercent, tierBorderColor } from '@/lib/utils'
import { RiskBadge, TierBadge, PersonaBadge } from '@/components/ui/Badge'
import { StatusDot } from '@/components/ui/StatusDot'
import { EmptyState } from '@/components/ui/EmptyState'
import { motion, AnimatePresence } from 'framer-motion'
import { Play, RefreshCw, ChevronDown, ChevronRight, MessageSquare, X, Zap } from 'lucide-react'

// ── Audit state (not persisted — lives for the duration of one audit run) ─
interface AuditRun {
  running: boolean
  done: boolean
  error: string | null
  personas: PersonaState[]
  iterations: IterationState[]
  currentIter: number
  findings: Finding[]
  redacted: string | null
  curve: CurvePoint[]
  metrics: RunMetrics | null
  feed: FeedEntry[]
}

interface FeedEntry {
  id: number
  who: string
  msg: string
  type: 'system' | 'persona' | 'finding' | 'error' | 'adjudicator' | 'guardian' | 'verify'
}

let _feedSeq = 0

function initialPersonas(): PersonaState[] {
  return PERSONAS.map(p => ({ id: p.id, label: p.label, status: 'idle', findings: 0, toolCalls: 0 }))
}

function initialRun(): AuditRun {
  return {
    running: false, done: false, error: null,
    personas: initialPersonas(),
    iterations: [], currentIter: 0,
    findings: [], redacted: null, curve: [],
    metrics: null, feed: [],
  }
}

export function AuditWorkspacePage() {
  const { auth, documents, selectedDocumentId, setSelectedDocumentId, updateDocument } = useApp()
  const [run, setRun] = useState<AuditRun>(initialRun)
  const [aggressiveness, setAggressiveness] = useState<'low' | 'balanced' | 'high'>('balanced')
  const [maxIterations, setMaxIterations] = useState(3)
  const [selectedPersonas, setSelectedPersonas] = useState<string[]>([
    'Layout-Forensicist',
    'Data-Broker',
    'Insider',
    'Journalist',
    'Stylometrist',
  ])
  const [selectedFinding, setSelectedFinding] = useState<Finding | null>(null)
  const [chatOpen, setChatOpen] = useState(false)
  const [chatMsg, setChatMsg] = useState('')
  const [chatHistory, setChatHistory] = useState<{ role: 'user' | 'assistant'; content: string }[]>([])
  const [chatLoading, setChatLoading] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)
  const feedRef = useRef<HTMLDivElement>(null)

  const selectedDoc = documents.find(d => d.document_id === selectedDocumentId) ?? null

  // Auto-scroll feed
  useEffect(() => {
    if (feedRef.current) {
      feedRef.current.scrollTop = feedRef.current.scrollHeight
    }
  }, [run.feed])

  function addFeed(who: string, msg: string, type: FeedEntry['type'] = 'system') {
    setRun(r => ({
      ...r,
      feed: [...r.feed, { id: _feedSeq++, who, msg, type }].slice(-200),
    }))
  }

  const handleEvent = useCallback((event: WsEvent) => {
    switch (event.event) {
      case 'iteration_start':
        setRun(r => ({
          ...r,
          currentIter: event.iteration,
          iterations: [...r.iterations, {
            iteration: event.iteration, status: 'running',
            findings: 0, risk: undefined, band: undefined, elapsedS: undefined,
          }],
          personas: initialPersonas(),
        }))
        addFeed('System', `Iteration ${event.iteration} / ${event.budget} — starting`, 'system')
        break

      case 'persona_start':
        setRun(r => ({
          ...r,
          personas: r.personas.map(p => p.id === event.persona ? { ...p, status: 'attacking' } : p),
        }))
        addFeed(event.persona, 'Attacking document…', 'persona')
        break

      case 'persona_done': {
        const hit = event.findings > 0
        setRun(r => ({
          ...r,
          personas: r.personas.map(p => p.id === event.persona ? {
            ...p, status: hit ? 'hit' : 'ok',
            findings: event.findings, toolCalls: event.tool_calls, elapsedS: event.elapsed_s,
          } : p),
        }))
        addFeed(event.persona,
          `${event.findings} finding${event.findings !== 1 ? 's' : ''} · ${event.tool_calls} tool call${event.tool_calls !== 1 ? 's' : ''} · ${event.elapsed_s}s`,
          hit ? 'finding' : 'persona')
        break
      }

      case 'persona_error':
        setRun(r => ({
          ...r,
          personas: r.personas.map(p => p.id === event.persona ? { ...p, status: 'error', error: event.error } : p),
        }))
        addFeed(event.persona, `Error: ${event.error}`, 'error')
        break

      case 'adjudicated':
        addFeed('Adjudicator',
          `${event.accepted} accepted · ${event.merged} merged · ${event.demoted} demoted`,
          'adjudicator')
        break

      case 'scored':
        setRun(r => ({
          ...r,
          iterations: r.iterations.map(it => it.iteration === r.currentIter ? {
            ...it, status: 'done',
            findings: event.risk.findings,
            risk: event.risk.residual_risk,
            band: event.risk.band,
            elapsedS: event.elapsed_s,
          } : it),
        }))
        addFeed('Scorer',
          `Risk ${(event.risk.residual_risk * 100).toFixed(0)} (${event.risk.band}) · Utility ${formatUtility(event.utility.utility_retained)}`,
          'system')
        break

      case 'repaired':
        addFeed('Guardian', `${event.edits} edit${event.edits !== 1 ? 's' : ''} applied · ${event.unrepaired} unrepaired`, 'guardian')
        break

      case 'verify_start':
        addFeed('System', 'Verification pass — re-attacking repaired document', 'verify')
        break

      case 'run_complete':
        setRun(r => ({ ...r, metrics: event.metrics }))
        if (event.stopped_because) addFeed('System', event.stopped_because, 'system')
        break

      case 'final':
        setRun(r => {
          const lastIter = r.iterations[r.iterations.length - 1]
          if (selectedDocumentId) {
            updateDocument(selectedDocumentId, {
              status: 'audited',
              lastBand: lastIter?.band,
              lastRisk: lastIter?.risk,
              lastUtility: event.curve?.[event.curve.length - 1]?.utility_retained,
            })
          }
          return { ...r, running: false, done: true, findings: event.findings, redacted: event.redacted, curve: event.curve ?? [] }
        })
        addFeed('System', `Audit complete — ${event.findings.length} finding${event.findings.length !== 1 ? 's' : ''}`, 'system')
        break

      case 'error':
        setRun(r => ({ ...r, running: false, error: event.detail }))
        addFeed('Error', event.detail, 'error')
        break
    }
  }, [selectedDocumentId, updateDocument])

  function startAudit() {
    if (!auth || !selectedDocumentId) return
    if (wsRef.current) wsRef.current.close()
    setRun({ ...initialRun(), running: true })
    addFeed('System', 'Audit started', 'system')

    wsRef.current = openAuditSocket({
      token: auth.token,
      documentId: selectedDocumentId,
      aggressiveness,
      maxIterations,
      targetRisk: 0.15,
      personas: selectedPersonas,
      onEvent: handleEvent,
      onClose: () => setRun(r => r.running ? { ...r, running: false, done: true } : r),
      onError: msg => { setRun(r => ({ ...r, running: false, error: msg })); addFeed('Error', msg, 'error') },
    })
  }

  async function sendChat() {
    if (!selectedDocumentId || !chatMsg.trim() || chatLoading) return
    const msg = chatMsg.trim()
    setChatMsg('')
    setChatHistory(h => [...h, { role: 'user', content: msg }])
    setChatLoading(true)
    try {
      const res = await api.chat(selectedDocumentId, msg)
      setChatHistory(h => [...h, { role: 'assistant', content: res.reply }])
    } catch {
      setChatHistory(h => [...h, { role: 'assistant', content: 'Chat unavailable — document may not have been audited yet.' }])
    } finally {
      setChatLoading(false)
    }
  }

  function stopAudit() {
    if (wsRef.current) {
      wsRef.current.close()
      addFeed('System', 'Audit stopped by user', 'system')
      setRun(r => ({ ...r, running: false, done: true }))
    }
  }

  if (!auth) return null
  const canRun = can(auth.role, 'run_attack')

  return (
    <div className="flex h-full overflow-hidden">
      {/* ── Left: controls + personas ─────────────────────────────────────── */}
      <div className="w-64 flex-shrink-0 border-r border-gray-200 bg-white flex flex-col overflow-y-auto">
        {/* Document selector */}
        <div className="p-4 border-b border-gray-100">
          <label className="section-label block mb-1.5">Document</label>
          <select
            value={selectedDocumentId ?? ''}
            onChange={e => setSelectedDocumentId(e.target.value || null)}
            className="w-full text-sm border border-gray-200 rounded-md px-2.5 py-1.5 outline-none focus:border-gray-400 bg-white"
          >
            <option value="">Select a document…</option>
            {documents.map(d => (
              <option key={d.document_id} value={d.document_id}>{d.filename}</option>
            ))}
          </select>
          {selectedDoc && (
            <p className="mt-1 text-2xs text-gray-400 font-mono">
              {selectedDoc.word_count.toLocaleString()}w · {selectedDoc.pages}p
            </p>
          )}
        </div>

        {/* Audit settings */}
        <div className="p-4 border-b border-gray-100">
          <p className="section-label mb-3">Audit settings</p>
          <div className="space-y-3">
            <div>
              <label className="text-xs text-gray-600 block mb-1">Aggressiveness</label>
              <select
                value={aggressiveness}
                onChange={e => setAggressiveness(e.target.value as 'low' | 'balanced' | 'high')}
                disabled={run.running}
                className="w-full text-sm border border-gray-200 rounded-md px-2.5 py-1.5 outline-none focus:border-gray-400 bg-white disabled:opacity-50"
              >
                <option value="low">Low</option>
                <option value="balanced">Balanced</option>
                <option value="high">High</option>
              </select>
            </div>
            <div>
              <label className="text-xs text-gray-600 block mb-1">Max iterations</label>
              <input
                type="number"
                value={maxIterations}
                onChange={e => setMaxIterations(Number(e.target.value))}
                min={1} max={5}
                disabled={run.running}
                className="w-full text-sm border border-gray-200 rounded-md px-2.5 py-1.5 outline-none focus:border-gray-400 disabled:opacity-50 font-mono"
              />
            </div>
          </div>

          {run.running ? (
            <button
              onClick={stopAudit}
              className="w-full mt-4 flex items-center justify-center gap-2 py-2 px-3 rounded-md text-sm font-medium transition-colors bg-red-600 text-white hover:bg-red-700"
            >
              <X size={13} /> Stop audit
            </button>
          ) : (
            <button
              onClick={startAudit}
              disabled={!canRun || !selectedDocumentId}
              className={cn(
                'w-full mt-4 flex items-center justify-center gap-2 py-2 px-3 rounded-md text-sm font-medium transition-colors',
                canRun && selectedDocumentId
                  ? 'bg-gray-900 text-white hover:bg-gray-800'
                  : 'bg-gray-100 text-gray-400 cursor-not-allowed',
              )}
            >
              <Play size={13} /> Run audit
            </button>
          )}

          {!canRun && (
            <p className="mt-2 text-2xs text-gray-400 text-center">Requires Auditor role</p>
          )}
        </div>

        {/* Persona status */}
        <div className="p-4 flex-1">
          <p className="section-label mb-3">Adversarial personas</p>
          <div className="space-y-2">
            {run.personas.map(p => (
              <PersonaCard
                key={p.id}
                persona={p}
                selected={selectedPersonas.includes(p.id)}
                disabled={run.running}
                onToggle={() => {
                  setSelectedPersonas(prev =>
                    prev.includes(p.id)
                      ? prev.filter(x => x !== p.id)
                      : [...prev, p.id]
                  )
                }}
              />
            ))}
          </div>
        </div>
      </div>

      {/* ── Center: live feed + metrics ───────────────────────────────────── */}
      <div className="flex flex-col flex-1 min-w-0 overflow-hidden border-r border-gray-200">
        {/* Iteration timeline bar */}
        {run.iterations.length > 0 && (
          <div className="flex items-center gap-2 px-4 py-2 border-b border-gray-100 bg-gray-50 overflow-x-auto flex-shrink-0">
            {run.iterations.map(it => (
              <IterationPill key={it.iteration} it={it} current={run.currentIter === it.iteration && run.running} />
            ))}
          </div>
        )}

        {/* Live feed */}
        <div className="flex items-center justify-between px-4 py-2 border-b border-gray-100 flex-shrink-0">
          <span className="section-label">Live feed</span>
          <span className="text-2xs text-gray-400 font-mono">
            {run.running ? 'Running' : run.done ? 'Complete' : 'Idle'}
          </span>
        </div>

        <div
          ref={feedRef}
          className="flex-1 overflow-y-auto px-4 py-3 space-y-1"
        >
          {run.feed.length === 0 ? (
            <EmptyState
              icon={<Zap />}
              title="No activity"
              description="Select a document and run an audit to see the live attack feed."
            />
          ) : (
            <AnimatePresence initial={false}>
              {run.feed.map(entry => (
                <motion.div
                  key={entry.id}
                  initial={{ opacity: 0, y: 2 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="flex items-start gap-2 py-1"
                >
                  <FeedChip who={entry.who} type={entry.type} />
                  <span className={cn(
                    'text-xs leading-relaxed',
                    entry.type === 'error' ? 'text-red-600' : 'text-gray-700',
                  )}>
                    {entry.msg}
                  </span>
                </motion.div>
              ))}
            </AnimatePresence>
          )}
        </div>

        {/* Metrics row */}
        {run.metrics && (
          <div className="border-t border-gray-100 px-4 py-3 flex-shrink-0 bg-gray-50">
            <p className="section-label mb-2">Inference metrics</p>
            <div className="grid grid-cols-3 gap-x-6 gap-y-1">
              {[
                ['Calls', run.metrics.calls],
                ['Prompt tokens', run.metrics.prompt_tokens?.toLocaleString()],
                ['Tokens/sec', run.metrics.mean_tokens_per_second?.toFixed(1)],
                ['Mean TTFT', run.metrics.mean_ttft_s != null ? `${run.metrics.mean_ttft_s}s` : '—'],
                ['Prefix cache hit', run.metrics.prefix_cache?.gpu_prefix_cache_hit_rate != null
                  ? `${(run.metrics.prefix_cache.gpu_prefix_cache_hit_rate * 100).toFixed(1)}%` : '—'],
                ['KV usage', run.metrics.prefix_cache?.gpu_cache_usage_perc != null
                  ? `${(run.metrics.prefix_cache.gpu_cache_usage_perc * 100).toFixed(1)}%` : '—'],
              ].map(([k, v]) => (
                <div key={k as string} className="flex items-baseline justify-between">
                  <span className="text-2xs text-gray-500">{k}</span>
                  <span className="text-2xs font-mono text-gray-700 tabular-nums">{v ?? '—'}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* ── Right: risk + findings ─────────────────────────────────────────── */}
      <div className="w-80 flex-shrink-0 bg-white flex flex-col overflow-hidden">
        {/* Risk gauge */}
        {(run.done || run.curve.length > 0) && (
          <RiskPanel run={run} />
        )}

        {/* Findings */}
        <div className="flex items-center justify-between px-4 pt-4 pb-2 flex-shrink-0">
          <span className="section-label">
            Findings {run.findings.length > 0 && `(${run.findings.length})`}
          </span>
          {run.done && can(auth.role, 'view_findings') && (
            <button
              onClick={() => setChatOpen(v => !v)}
              className={cn(
                'text-2xs text-gray-500 hover:text-gray-900 flex items-center gap-1 transition-colors',
                chatOpen && 'text-gray-900',
              )}
            >
              <MessageSquare size={12} /> Ask VEIL
            </button>
          )}
        </div>

        <div className="flex-1 overflow-y-auto px-4 pb-4">
          {run.findings.length === 0 ? (
            <div className="text-xs text-gray-400 py-4">
              {run.done ? 'No surviving findings.' : 'Waiting for findings…'}
            </div>
          ) : (
            <div className="space-y-2">
              {run.findings.map(f => (
                <FindingCard
                  key={f.id}
                  finding={f}
                  selected={selectedFinding?.id === f.id}
                  onSelect={() => setSelectedFinding(sf => sf?.id === f.id ? null : f)}
                  role={auth.role}
                />
              ))}
            </div>
          )}
        </div>

        {/* Chat panel */}
        {chatOpen && run.done && selectedDocumentId && (
          <div className="border-t border-gray-200 flex flex-col" style={{ height: '280px' }}>
            <div className="flex items-center justify-between px-3 py-2 border-b border-gray-100">
              <span className="text-xs font-medium text-gray-700">VEIL Chat</span>
              <button onClick={() => setChatOpen(false)} className="text-gray-400 hover:text-gray-600">
                <X size={13} />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto px-3 py-2 space-y-2 text-xs">
              {chatHistory.length === 0 && (
                <p className="text-gray-400">Ask about findings, redaction decisions, or risk scores.</p>
              )}
              {chatHistory.map((m, i) => (
                <div key={i} className={cn('leading-relaxed', m.role === 'user' ? 'text-gray-900 font-medium' : 'text-gray-600')}>
                  <span className="text-2xs text-gray-400 mr-1">{m.role === 'user' ? 'You' : 'VEIL'}:</span>
                  {m.content}
                </div>
              ))}
              {chatLoading && <p className="text-gray-400">Thinking…</p>}
            </div>
            <div className="border-t border-gray-100 p-2 flex gap-2">
              <input
                value={chatMsg}
                onChange={e => setChatMsg(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && sendChat()}
                placeholder="Ask a question…"
                className="flex-1 text-xs px-2 py-1.5 border border-gray-200 rounded outline-none focus:border-gray-400"
              />
              <button
                onClick={sendChat}
                disabled={chatLoading || !chatMsg.trim()}
                className="px-2.5 py-1.5 text-xs bg-gray-900 text-white rounded disabled:opacity-40"
              >
                Send
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Sub-components ─────────────────────────────────────────────────────────

function PersonaCard({
  persona,
  selected,
  disabled,
  onToggle,
}: {
  persona: PersonaState
  selected: boolean
  disabled: boolean
  onToggle: () => void
}) {
  const statusColors: Record<string, string> = {
    idle:      'text-gray-400',
    attacking: 'text-blue-600',
    hit:       'text-amber-600',
    ok:        'text-green-600',
    error:     'text-red-600',
  }
  return (
    <div
      onClick={() => { if (!disabled) onToggle() }}
      className={cn(
        'flex items-center gap-2.5 p-2 rounded-md border transition-colors text-xs select-none',
        !selected                      ? 'border-gray-100 bg-gray-50/50 opacity-40' :
        persona.status === 'attacking' ? 'border-blue-100 bg-blue-50' :
        persona.status === 'hit'       ? 'border-amber-100 bg-amber-50' :
        persona.status === 'ok'        ? 'border-green-100 bg-green-50' :
        persona.status === 'error'     ? 'border-red-100 bg-red-50' :
                                         'border-gray-100 hover:border-gray-300',
        !disabled && 'cursor-pointer',
      )}
    >
      <input
        type="checkbox"
        checked={selected}
        disabled={disabled}
        onChange={(e) => {
          e.stopPropagation()
          onToggle()
        }}
        className="rounded text-gray-900 focus:ring-gray-900 disabled:opacity-40"
      />
      <div className="flex-1 min-w-0">
        <p className="font-medium text-gray-800 truncate text-xs">{persona.label}</p>
        {selected && persona.status !== 'idle' && (
          <p className={cn('text-2xs font-mono', statusColors[persona.status])}>
            {persona.status === 'attacking' ? 'attacking…' :
             persona.status === 'hit' ? `${persona.findings}f · ${persona.toolCalls}t` :
             persona.status === 'ok'  ? `clean · ${persona.toolCalls}t` :
             persona.status === 'error' ? 'failed' : ''}
          </p>
        )}
      </div>
    </div>
  )
}

function IterationPill({ it, current }: { it: IterationState; current: boolean }) {
  return (
    <div className={cn(
      'flex items-center gap-2 px-3 py-1.5 rounded-full border text-xs font-mono flex-shrink-0',
      current ? 'border-blue-200 bg-blue-50 text-blue-700' :
      it.status === 'done' && it.band ? 'border-gray-200 bg-white text-gray-700' :
                                        'border-gray-200 bg-white text-gray-400',
    )}>
      <span>#{it.iteration}</span>
      {current && <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />}
      {it.band && !current && <RiskBadge band={it.band as RiskBand} />}
      {it.findings != null && !current && (
        <span className="text-gray-400">{it.findings}f</span>
      )}
    </div>
  )
}

function FeedChip({ who, type }: { who: string; type: FeedEntry['type'] }) {
  const styles = {
    system:      'bg-gray-100 text-gray-500',
    persona:     'bg-blue-50 text-blue-700',
    finding:     'bg-amber-50 text-amber-700',
    error:       'bg-red-50 text-red-700',
    adjudicator: 'bg-green-50 text-green-700',
    guardian:    'bg-sky-50 text-sky-700',
    verify:      'bg-purple-50 text-purple-700',
  }[type]

  return (
    <span className={cn(
      'inline-block px-1.5 py-0.5 rounded text-2xs font-mono flex-shrink-0 whitespace-nowrap',
      styles,
    )}>
      {who}
    </span>
  )
}

function RiskPanel({ run }: { run: AuditRun }) {
  const lastIter = run.iterations[run.iterations.length - 1]
  const risk = lastIter?.risk ?? 0
  const band = lastIter?.band
  const lastCurve = run.curve[run.curve.length - 1]
  const util = lastCurve?.utility_retained ?? 0

  return (
    <div className="px-4 pt-4 pb-3 border-b border-gray-100 flex-shrink-0">
      <div className="grid grid-cols-2 gap-3 mb-3">
        <div>
          <p className="section-label mb-1">Residual risk</p>
          <div className="flex items-baseline gap-2">
            <span className={cn(
              'text-2xl font-bold tabular-nums',
              band === 'CRITICAL' ? 'text-red-700' :
              band === 'HIGH'     ? 'text-amber-700' :
              band === 'MEDIUM'   ? 'text-sky-700' :
                                    'text-green-700',
            )}>
              {(risk * 100).toFixed(0)}
            </span>
            <span className="text-xs text-gray-400">/ 100</span>
          </div>
          <div className="mt-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
            <div
              className={cn(
                'h-full rounded-full transition-all duration-700',
                band === 'CRITICAL' ? 'bg-red-500' :
                band === 'HIGH'     ? 'bg-amber-500' :
                band === 'MEDIUM'   ? 'bg-sky-500' :
                                      'bg-green-500',
              )}
              style={{ width: `${riskToPercent(risk)}%` }}
            />
          </div>
          {band && <RiskBadge band={band} />}
        </div>
        <div>
          <p className="section-label mb-1">Utility retained</p>
          <span className="text-2xl font-bold tabular-nums text-gray-700">
            {formatUtility(util)}
          </span>
          <div className="mt-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
            <div
              className="h-full rounded-full bg-gray-400 transition-all duration-700"
              style={{ width: `${util * 100}%` }}
            />
          </div>
        </div>
      </div>
    </div>
  )
}

function FindingCard({ finding, selected, onSelect, role }: {
  finding: Finding; selected: boolean; onSelect: () => void; role: string
}) {
  return (
    <div
      className={cn(
        'rounded-md border-l-2 border border-gray-200 p-3 cursor-pointer transition-colors',
        tierBorderColor(finding.tier),
        selected ? 'bg-gray-50 border-gray-300' : 'hover:bg-gray-50',
        finding.resolved && 'opacity-50',
      )}
      onClick={onSelect}
    >
      <div className="flex items-center gap-2 mb-2 flex-wrap">
        <TierBadge tier={finding.tier} />
        <PersonaBadge name={finding.persona} />
        {finding.resolved && <span className="text-2xs text-gray-400 ml-auto">Resolved</span>}
        <button className="ml-auto text-gray-300 hover:text-gray-500 transition-colors">
          {selected ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        </button>
      </div>

      {finding.claim ? (
        <p className="text-xs text-gray-800 leading-relaxed">{finding.claim}</p>
      ) : (
        <p className="text-xs text-gray-400 italic">Claim withheld for your role</p>
      )}

      <div className="mt-2 flex items-center gap-3">
        <span className="text-2xs font-mono text-gray-400 tabular-nums">
          severity {(finding.severity * 100).toFixed(0)}
        </span>
        {finding.candidate_set_size != null && (
          <span className="text-2xs font-mono text-gray-400">k={finding.candidate_set_size}</span>
        )}
      </div>

      {/* Expanded detail */}
      <AnimatePresence>
        {selected && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            <div className="mt-3 pt-3 border-t border-gray-100">
              {finding.caveat && (
                <p className="text-2xs text-amber-700 mb-2">⚠ {finding.caveat}</p>
              )}
              {finding.reasoning && (
                <div>
                  <p className="section-label mb-1">Reasoning (Auditor)</p>
                  <p className="text-2xs text-gray-600 leading-relaxed font-mono whitespace-pre-wrap">
                    {finding.reasoning}
                  </p>
                </div>
              )}
              {finding.spans && finding.spans.length > 0 && (
                <div className="mt-2">
                  <p className="section-label mb-1">Evidence spans</p>
                  {finding.spans.slice(0, 3).map((s, i) => (
                    <div key={i} className="mt-1 p-2 bg-amber-50 border border-amber-100 rounded text-2xs font-mono text-amber-900 truncate">
                      "{s.text}"
                    </div>
                  ))}
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
