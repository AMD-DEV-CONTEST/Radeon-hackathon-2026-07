import { Bot, Wrench, CheckCircle2, AlertTriangle } from 'lucide-react'

interface StreamEvent {
  type: string
  payload: Record<string, unknown>
  from?: string
  timestamp?: string
}

interface AgentStreamPanelProps {
  agentName: string
  status: string
  events: StreamEvent[]
  opinion?: string
}

const statusBadge: Record<string, { color: string; label: string }> = {
  online_idle: { color: '#64748b', label: '待命' },
  in_session_idle: { color: '#3b82f6', label: '就位' },
  running: { color: '#22c55e', label: '执行中' },
  offline: { color: '#ef4444', label: '离线' },
}

function eventPreview(event: StreamEvent): string {
  const t = event.type
  const p = event.payload || {}
  if (t === 'tool_use') return `$ ${p.tool_name || 'tool'} ${JSON.stringify(p.input || {}).slice(0, 40)}`
  if (t === 'tool_result') return `→ ${String(p.content || '').slice(0, 50)}`
  if (t === 'text') return String(p.content || '').slice(0, 60)
  if (t === 'thinking') return `🧠 ${String(p.content || '').slice(0, 60)}`
  if (t === 'finish') return `✅ ${String(p.summary || '').slice(0, 60)}`
  if (t === 'done') return `✓ done`
  if (t === 'warning') return `⚠ ${String(p.message || '')}`
  if (t === 'error') return `❌ ${String(p.message || '')}`
  if (t === 'phase') return `▶ ${p.phase}: ${p.status}`
  if (t === 'block') return `🚫 ${p.block_type}: ${String(p.message || '').slice(0, 40)}`
  return t
}

export function AgentStreamPanel({ agentName, status, events, opinion }: AgentStreamPanelProps) {
  const badge = statusBadge[status] || { color: '#64748b', label: status }
  const recent = events.slice(-5)
  const hasOutput = recent.length > 0
  const lastTool = recent.filter(e => e.type === 'tool_use').slice(-1)[0]
  const lastText = recent.filter(e => e.type === 'text' || e.type === 'thinking').slice(-1)[0]

  return (
    <div className={`agent-stream-card ${status}`}>
      <div className="asc-header">
        <Bot size={18} className="asc-icon" />
        <span className="asc-name">{agentName}</span>
        <span className="asc-badge" style={{ background: badge.color }}>{badge.label}</span>
      </div>

      {opinion && (
        <div className="asc-opinion">
          <div className="asc-opinion-text">"{opinion}"</div>
          <div className="asc-opinion-sig">— {agentName} 署名</div>
        </div>
      )}

      <div className="asc-output">
        {!hasOutput && !opinion && (
          <div className="asc-empty">等待输出...</div>
        )}
        {lastText && (
          <div className="asc-last-text">
            <span className="asc-last-label">最近发言</span>
            {eventPreview(lastText)}
          </div>
        )}
        {lastTool && (
          <div className="asc-last-tool">
            <Wrench size={12} />
            {eventPreview(lastTool)}
          </div>
        )}
        {recent.filter(e => e.type === 'finish' || e.type === 'done').map((e, i) => (
          <div key={i} className="asc-finish">
            <CheckCircle2 size={12} />
            {eventPreview(e)}
          </div>
        ))}
        {recent.filter(e => e.type === 'error' || e.type === 'warning').map((e, i) => (
          <div key={i} className="asc-issue">
            <AlertTriangle size={12} />
            {eventPreview(e)}
          </div>
        ))}
      </div>
    </div>
  )
}
