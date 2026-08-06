import { useEffect, useRef, useState } from 'react'
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  ClipboardList,
  Flag,
  Maximize2,
  MessageSquare,
  Minus,
  Package,
  Rocket,
  ScrollText,
  TerminalSquare,
  X,
} from 'lucide-react'
import type { SessionRole } from './DormSidebar'

export interface AgentWindowState {
  id: string
  participantId: string
  terminalId: string
  agentId: string
  agentName: string
  agentType: string
  machineName: string
  role: SessionRole
  status: 'summoned' | 'joined' | 'running' | 'done' | 'blocked' | 'left'
  wsUrl: string
  x: number
  y: number
  width: number
  height: number
  z: number
  minimized: boolean
  seatColor?: string
  instruction?: string
  delivery?: string
  feedback?: string
  auditOpinion?: string
  deploymentOpinion?: string
  nextDecision?: string
}

interface AgentWindowProps {
  window: AgentWindowState
  focused: boolean
  sessionId: string | null
  currentRound: number
  onFocus: (id: string) => void
  onPatch: (id: string, patch: Partial<AgentWindowState>) => void
  onMinimize: (id: string) => void
  onClose: (id: string) => void
  onLeaderSubmit?: (kind: 'audit' | 'deployment' | 'decision', value: string | undefined) => Promise<void>
}

function statusColor(status: AgentWindowState['status']): string {
  switch (status) {
    case 'running':  return '#22c55e'
    case 'joined':
    case 'summoned': return '#3b82f6'
    case 'blocked':  return '#eab308'
    case 'done':     return '#22c55e'
    case 'left':     return '#6b7280'
    default:         return '#6b7280'
  }
}

function statusLabel(status: AgentWindowState['status']): string {
  switch (status) {
    case 'summoned': return '已召唤'
    case 'joined':   return '已就位'
    case 'running':  return '工作中'
    case 'done':     return '已完成'
    case 'blocked':  return '阻塞'
    case 'left':     return '已离开'
  }
}

const SEAT_PALETTE: Record<string, string> = {
  reasonix: 'rgba(148, 163, 184, 0.06)',
  codex:    'rgba(251, 191, 36, 0.04)',
  claude:   'rgba(249, 115, 22, 0.04)',
  scc:      'rgba(34, 197, 94, 0.04)',
  hermes:   'rgba(59, 130, 246, 0.04)',
  opencode: 'rgba(168, 85, 247, 0.04)',
}

function seatBg(agentType: string, role: SessionRole): string {
  if (role === 'leader') return 'rgba(203, 213, 225, 0.06)'
  return SEAT_PALETTE[agentType] ?? 'rgba(148, 163, 184, 0.03)'
}

export function AgentWindow({
  window,
  focused,
  sessionId,
  currentRound,
  onFocus,
  onPatch,
  onMinimize,
  onClose,
  onLeaderSubmit,
}: AgentWindowProps) {
  const shellRef = useRef<HTMLDivElement | null>(null)
  const outputRef = useRef<HTMLDivElement | null>(null)
  const inputRef = useRef<HTMLTextAreaElement | null>(null)
  const socketRef = useRef<WebSocket | null>(null)
  const [output, setOutput] = useState<string[]>([])
  const [showInstruction, setShowInstruction] = useState(true)
  const [showDelivery, setShowDelivery] = useState(false)
  const [showFeedback, setShowFeedback] = useState(false)
  const [leaderSubmitting, setLeaderSubmitting] = useState<string | null>(null)

  const isLeader = window.role === 'leader'
  const color = statusColor(window.status)
  const bg = window.seatColor ?? seatBg(window.agentType, window.role)

  useEffect(() => {
    if (window.minimized) return

    const ws = new WebSocket(window.wsUrl)
    socketRef.current = ws

    ws.onopen = () => {
      onPatch(window.id, { status: 'joined' })
    }
    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data) as { type?: string; data?: string; exit_code?: number }
        if (msg.type === 'stdout' || msg.type === 'stderr') {
          setOutput((prev) => [...prev, msg.data ?? ''].slice(-2000))
          return
        }
        if (msg.type === 'exit') {
          setOutput((prev) => [...prev, `\r\n[process exited ${msg.exit_code ?? ''}]`].slice(-2000))
          onPatch(window.id, { status: 'done' })
          return
        }
        setOutput((prev) => [...prev, String(event.data)].slice(-2000))
      } catch {
        setOutput((prev) => [...prev, String(event.data)].slice(-2000))
      }
    }
    ws.onerror = () => {
      setOutput((prev) => [...prev, '\r\n[connection error]'].slice(-2000))
      onPatch(window.id, { status: 'blocked' })
    }
    ws.onclose = () => {
      setOutput((prev) => [...prev, '\r\n[disconnected]'].slice(-2000))
    }

    return () => {
      ws.close()
      socketRef.current = null
    }
  }, [window.wsUrl, window.id, window.minimized, onPatch])

  // Auto-scroll output
  useEffect(() => {
    if (outputRef.current) {
      outputRef.current.scrollTop = outputRef.current.scrollHeight
    }
  }, [output])

  // Focus input when window is focused
  useEffect(() => {
    if (focused && inputRef.current) {
      inputRef.current.focus()
    }
  }, [focused])

  const handleInput = (text: string) => {
    const ws = socketRef.current
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'stdin', data: text }))
    }
  }

  const submitLeaderOpinion = async (
    kind: 'audit' | 'deployment' | 'decision',
    value: string | undefined,
  ) => {
    if (!onLeaderSubmit || !sessionId || !value?.trim()) return
    setLeaderSubmitting(kind)
    try {
      await onLeaderSubmit(kind, value)
      if (kind === 'audit') onPatch(window.id, { auditOpinion: '' })
      if (kind === 'deployment') onPatch(window.id, { deploymentOpinion: '' })
      if (kind === 'decision') onPatch(window.id, { nextDecision: '' })
    } finally {
      setLeaderSubmitting(null)
    }
  }

  if (window.minimized) return null

  return (
    <div
      ref={shellRef}
      className={`agent-window ${focused ? 'focused' : ''} ${window.status}`}
      style={{
        left: window.x,
        top: window.y,
        width: window.width,
        height: window.height,
        zIndex: window.z,
        background: `linear-gradient(135deg, ${bg} 0%, #0f172a 100%)`,
      }}
      onMouseDown={() => onFocus(window.id)}
    >
      {/* Status color strip */}
      <div className="agent-window-status-strip" style={{ background: color }} />

      {/* Titlebar */}
      <div
        className="agent-window-titlebar"
        onMouseDown={(event) => {
          event.preventDefault()
          onFocus(window.id)
          const startX = event.clientX
          const startY = event.clientY
          const originX = window.x
          const originY = window.y
          const move = (moveEvent: MouseEvent) => {
            onPatch(window.id, {
              x: Math.max(0, originX + moveEvent.clientX - startX),
              y: Math.max(0, originY + moveEvent.clientY - startY),
            })
          }
          document.addEventListener('mousemove', move)
          document.addEventListener('mouseup', () => {
            document.removeEventListener('mousemove', move)
          }, { once: true })
        }}
      >
        <TerminalSquare size={15} color={color} />
        <div className="agent-window-title">
          <strong>
            {window.agentName}
            {isLeader && <span className="leader-badge">Leader</span>}
          </strong>
          <span>{window.machineName} · {window.role} · {statusLabel(window.status)}</span>
        </div>
        <div className="agent-window-actions">
          <button onClick={(event) => { event.stopPropagation(); onMinimize(window.id) }} title="Minimize">
            <Minus size={13} />
          </button>
          <button
            onClick={(event) => {
              event.stopPropagation()
              onPatch(window.id, { width: 800, height: 600, x: 24, y: 24 })
            }}
            title="Maximize"
          >
            <Maximize2 size={13} />
          </button>
          <button
            onClick={(event) => {
              event.stopPropagation()
              if (globalThis.confirm('Close this AgentWindow?')) {
                onClose(window.id)
              }
            }}
            title="Close"
          >
            <X size={13} />
          </button>
        </div>
      </div>

      {/* Instruction zone */}
      <div className="agent-window-zone">
        <button className="zone-toggle" onClick={() => setShowInstruction((v) => !v)}>
          {showInstruction ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          <ClipboardList size={12} />
          <span>指令区</span>
        </button>
        {showInstruction && (
          <div className="zone-body instruction-zone">
            {window.instruction ? (
              <p>{window.instruction}</p>
            ) : (
              <p className="zone-placeholder">等待 Leader 发布本轮指令...</p>
            )}
          </div>
        )}
      </div>

      {/* Terminal: textarea-based, no xterm.js */}
      <div
        ref={outputRef}
        className="agent-window-terminal-native"
        onMouseDown={() => {
          onFocus(window.id)
          setTimeout(() => inputRef.current?.focus(), 0)
        }}
      >
        {output.length === 0 ? (
          <span className="terminal-waiting">等待连接...</span>
        ) : (
          output.map((line, i) => <span key={i}>{line}</span>)
        )}
      </div>
      <textarea
        ref={inputRef}
        className="agent-window-input"
        rows={1}
        placeholder="输入命令后回车..."
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            const text = e.currentTarget.value + '\r\n'
            handleInput(text)
            e.currentTarget.value = ''
          }
        }}
      />

      {/* Delivery zone */}
      <div className="agent-window-zone">
        <button className="zone-toggle" onClick={() => setShowDelivery((v) => !v)}>
          {showDelivery ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          <Package size={12} />
          <span>任务交付区</span>
          {window.delivery && <CheckCircle2 size={10} color="#22c55e" />}
        </button>
        {showDelivery && (
          <div className="zone-body delivery-zone">
            {window.delivery ? <p>{window.delivery}</p> : <p className="zone-placeholder">暂无交付物</p>}
          </div>
        )}
      </div>

      {/* FBE feedback zone */}
      <div className="agent-window-zone">
        <button className="zone-toggle" onClick={() => setShowFeedback((v) => !v)}>
          {showFeedback ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          {window.status === 'blocked' ? <AlertTriangle size={12} color="#eab308" /> : <MessageSquare size={12} />}
          <span>FBE 反馈区</span>
        </button>
        {showFeedback && (
          <div className="zone-body feedback-zone">
            {window.feedback ? <p>{window.feedback}</p> : <p className="zone-placeholder">无阻塞或反馈</p>}
          </div>
        )}
      </div>

      {/* Leader-only zones */}
      {isLeader && (
        <div className="agent-window-leader-zones">
          <div className="leader-zone">
            <ScrollText size={11} />
            <span>审计意见</span>
            <button
              className="leader-submit-btn"
              disabled={!onLeaderSubmit || leaderSubmitting !== null || !window.auditOpinion?.trim()}
              onClick={(e) => { e.stopPropagation(); void submitLeaderOpinion('audit', window.auditOpinion) }}
              title={`Submit audit for round ${currentRound}`}
            >
              Submit
            </button>
            <textarea
              className="leader-zone-input"
              rows={2}
              placeholder="本轮交付是否接受、退回、补测..."
              value={window.auditOpinion ?? ''}
              onChange={(e) => onPatch(window.id, { auditOpinion: e.target.value })}
              onClick={(e) => e.stopPropagation()}
            />
          </div>
          <div className="leader-zone">
            <Rocket size={11} />
            <span>部署意见</span>
            <button
              className="leader-submit-btn"
              disabled={!onLeaderSubmit || leaderSubmitting !== null || !window.deploymentOpinion?.trim()}
              onClick={(e) => { e.stopPropagation(); void submitLeaderOpinion('deployment', window.deploymentOpinion) }}
              title={`Submit deployment for round ${currentRound}`}
            >
              Submit
            </button>
            <textarea
              className="leader-zone-input"
              rows={2}
              placeholder="能否部署、部署风险、回滚点..."
              value={window.deploymentOpinion ?? ''}
              onChange={(e) => onPatch(window.id, { deploymentOpinion: e.target.value })}
              onClick={(e) => e.stopPropagation()}
            />
          </div>
          <div className="leader-zone">
            <Flag size={11} />
            <span>下一轮决策</span>
            <button
              className="leader-submit-btn"
              disabled={!onLeaderSubmit || leaderSubmitting !== null || !window.nextDecision}
              onClick={(e) => { e.stopPropagation(); void submitLeaderOpinion('decision', window.nextDecision) }}
              title={`Submit decision for round ${currentRound}`}
            >
              Submit
            </button>
            <select
              className="leader-zone-select"
              value={window.nextDecision ?? ''}
              onChange={(e) => onPatch(window.id, { nextDecision: e.target.value })}
              onClick={(e) => e.stopPropagation()}
            >
              <option value="">— 选择 —</option>
              <option value="continue">继续</option>
              <option value="rework">返工</option>
              <option value="reassign">换人</option>
              <option value="deploy">部署</option>
              <option value="accept">验收</option>
              <option value="dismiss">散会</option>
            </select>
          </div>
        </div>
      )}

      {/* Resize handle */}
      <div
        className="agent-window-resize"
        onMouseDown={(event) => {
          event.preventDefault()
          event.stopPropagation()
          const startX = event.clientX
          const startY = event.clientY
          const originWidth = window.width
          const originHeight = window.height
          const move = (moveEvent: MouseEvent) => {
            onPatch(window.id, {
              width: Math.max(420, originWidth + moveEvent.clientX - startX),
              height: Math.max(500, originHeight + moveEvent.clientY - startY),
            })
          }
          document.addEventListener('mousemove', move)
          document.addEventListener('mouseup', () => document.removeEventListener('mousemove', move), { once: true })
        }}
      />
    </div>
  )
}
