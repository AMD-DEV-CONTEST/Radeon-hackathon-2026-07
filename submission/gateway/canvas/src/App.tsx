import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent as ReactMouseEvent, type WheelEvent } from 'react'
import {
  Activity,
  AlertTriangle,
  Bot,
  CheckCircle2,
  CirclePlus,
  Clock3,
  GitBranch,
  Loader2,
  LocateFixed,
  Megaphone,
  Minus,
  Play,
  Plus,
  RefreshCw,
  ShieldCheck,
  Square,
  ZoomIn,
  ZoomOut,
  X,
} from 'lucide-react'
import { Terminal } from '@xterm/xterm'
import '@xyflow/react/dist/style.css'
import '@xterm/xterm/css/xterm.css'
import './App.css'
import { LayoutToolbar, type LayoutConfig } from './LayoutToolbar'
import { ChatInput } from './ChatInput'
import { StagePipeline, type StageName, type StageState } from './StagePipeline'
import { DormSidebar, type DormAgent, type DormMachine, type SessionRole } from './DormSidebar'
import { WindowManager } from './WindowManager'
import type { AgentWindowState } from './AgentWindow'
// applyLayout removed — no longer using ReactFlow nodes
import { StatusFooter } from './StatusFooter'
import { SessionRecord, type SessionRecordEvent } from './SessionRecord'
import { useSessionStage } from './useSessionStage'
import { RoundPanel } from './RoundPanel'
import { TaskPanel } from './TaskPanel'

const API_BASE = import.meta.env.VITE_ORCHESTRATOR_URL ?? 'http://111.228.42.18:8000'
const STREAMING_BASE = import.meta.env.VITE_STREAMING_URL ?? 'http://111.228.42.18:8001'

type Task = {
  id: string
  parent_task_id: string | null
  title: string
  description: string
  task_type: string
  status: string
  priority: number
  dependencies: string[]
  required_capabilities: Record<string, unknown>
  acceptance_check: Record<string, unknown>
  payload: Record<string, unknown>
  max_attempts: number
  lease_owner: string | null
  lease_expires_at: string | null
  blocked_until: string | null
  created_by: string
  created_at: string
  updated_at: string
  finished_at: string | null
  attempt_id?: string | null
  attempt_no?: number | null
}

type Agent = {
  id: string
  name: string
  agent_type: string
  host_id: string
  status: string
  os: string
  shell: string | null
  last_heartbeat_at: string | null
  created_at: string | null
  capabilities?: Record<string, unknown>
  max_concurrency?: number
}

type EventItem = {
  id: string
  task_id: string | null
  attempt_id: string | null
  agent_id: string | null
  event_type: string
  message: string
  level: string
  payload: Record<string, unknown>
  created_at: string
}

type AgentOutputType =
  | 'init'
  | 'thinking'
  | 'tool_use'
  | 'tool_result'
  | 'text'
  | 'warning'
  | 'error'
  | 'phase'
  | 'block'
  | 'finish'
  | 'done'
  | 'heartbeat'

type AgentStreamEvent = {
  session_id: string
  msg_id: string
  agent_id: string
  type: AgentOutputType
  payload: Record<string, unknown>
  timestamp: string
}

type CreateTaskForm = {
  title: string
  description: string
  task_type: string
  instruction: string
  required_capabilities: string
  acceptance_check: string
}

type AgentTemplate = {
  label: string
  agent_type: Agent['agent_type']
  defaultName: string
  capabilities: Record<string, unknown>
}

type GatewayHealth = {
  status: string
  agents_online: number
  agents?: Array<{
    agent_id: string
    agent_name: string
    agent_type: string
    status: string
  }>
  cost_guard?: Record<string, { active: number; max?: number | null }>
  sessions?: Array<{
    session_id: string
    status: string
    participants: string[]
    connections: number
  }>
}

type BroadcastForm = {
  goal: string
  selectedAgentIds: string[]
  maxCodex: number
  maxScc: number
  maxReasonix: number
  maxHermes: number
}


type GatewaySessionCreateResponse = {
  session_id: string
}

type ParticipantCreateResponse = {
  participant_id: string
  terminal_id: string
  pty_ws_url: string
  status: string
}

const statusColor: Record<string, string> = {
  queued: '#94a3b8',
  leased: '#3b82f6',
  running: '#3b82f6',
  done: '#22c55e',
  failed_retryable: '#ef4444',
  failed_final: '#991b1b',
  blocked_auth: '#f59e0b',
  blocked_rate_limit: '#f59e0b',
  blocked_env: '#f59e0b',
  blocked_permission: '#f59e0b',
  timeout_silent: '#ef4444',
  needs_review: '#a855f7',
  cancelled: '#6b7280',
}

const taskTypes = [
  'feature-implementation',
  'refactor',
  'debug',
  'lint-fix',
  'doc-update',
  'test-gen',
  'architecture-review',
]

const agentTemplates: AgentTemplate[] = [
  {
    label: 'Hub',
    agent_type: 'generic',
    defaultName: 'hub-01',
    capabilities: { agent: 'hub', hub: true },
  },
  {
    label: 'CC review',
    agent_type: 'claude_code',
    defaultName: 'cc-review-01',
    capabilities: { agent: 'claude', review: true },
  },
  {
    label: 'Reasonix',
    agent_type: 'reasonix',
    defaultName: 'reasonix-01',
    capabilities: { agent: 'reasonix', coding: true },
  },
  {
    label: 'Codex',
    agent_type: 'codex',
    defaultName: 'codex-01',
    capabilities: { agent: 'codex', coding: true },
  },
]

const emptyForm: CreateTaskForm = {
  title: '',
  description: '',
  task_type: 'feature-implementation',
  instruction: '',
  required_capabilities: '{\n  "agent": "reasonix"\n}',
  acceptance_check: '{\n  "type": "manual"\n}',
}

const emptyBroadcast: BroadcastForm = {
  goal: '',
  selectedAgentIds: [],
  maxCodex: 1,
  maxScc: 1,
  maxReasonix: 2,
  maxHermes: 1,
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...init?.headers,
    },
  })
  if (!response.ok) {
    const detail = await response.text()
    throw new Error(`${response.status} ${response.statusText}: ${detail}`)
  }
  return response.json() as Promise<T>
}

async function streamingApi<T>(path: string, init?: RequestInit, token?: string, onAuthError?: () => void): Promise<T> {
  const authHeaders: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {}
  const response = await fetch(`${STREAMING_BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...authHeaders,
      ...init?.headers,
    },
  })
  if (response.status === 401 || response.status === 403) {
    onAuthError?.()
    throw new Error(`auth_error: ${response.status}`)
  }
  if (!response.ok) {
    const detail = await response.text()
    throw new Error(`${response.status} ${response.statusText}: ${detail}`)
  }
  return response.json() as Promise<T>
}

function parseJsonField(value: string, fallback: Record<string, unknown>) {
  const trimmed = value.trim()
  if (!trimmed) return fallback
  return JSON.parse(trimmed) as Record<string, unknown>
}

function streamLine(event: AgentStreamEvent) {
  if (event.type === 'text') return String(event.payload.content ?? '')
  if (event.type === 'thinking') return String(event.payload.content ?? '')
  if (event.type === 'tool_use') return `$ ${String(event.payload.tool_name ?? 'tool')}`
  if (event.type === 'tool_result') return String(event.payload.content ?? '')
  if (event.type === 'warning') return `warn: ${String(event.payload.message ?? '')}`
  if (event.type === 'error') return `error: ${String(event.payload.message ?? '')}`
  if (event.type === 'phase') {
    return `${String(event.payload.phase ?? 'phase')}: ${String(event.payload.status ?? '')}`
  }
  if (event.type === 'finish') return `finish: ${String(event.payload.summary ?? '')}`
  if (event.type === 'done') return 'done'
  return event.type
}

function TerminalPanel({ events, sessionId }: { events: AgentStreamEvent[]; sessionId: string }) {
  const elementRef = useRef<HTMLDivElement | null>(null)
  const terminalRef = useRef<Terminal | null>(null)
  const writtenRef = useRef(0)

  useEffect(() => {
    if (!elementRef.current) return
    const terminal = new Terminal({
      cursorBlink: false,
      convertEol: true,
      fontFamily: 'Consolas, "SFMono-Regular", monospace',
      fontSize: 12,
      rows: 12,
      theme: {
        background: '#0f172a',
        foreground: '#e2e8f0',
      },
    })
    terminal.open(elementRef.current)
    terminalRef.current = terminal
    terminal.writeln(`session ${sessionId}`)
    terminal.writeln(`stream ${STREAMING_BASE}/stream/sessions/${sessionId}`)
    terminal.writeln('')
    writtenRef.current = 0
    return () => {
      terminal.dispose()
      terminalRef.current = null
    }
  }, [sessionId])

  useEffect(() => {
    const terminal = terminalRef.current
    if (!terminal) return
    events.slice(writtenRef.current).forEach((event) => {
      terminal.writeln(`[${event.type}] ${streamLine(event).trimEnd()}`)
    })
    writtenRef.current = events.length
  }, [events])

  return <div ref={elementRef} className="terminal-panel" />
}

function formatTime(value: string | null) {
  if (!value) return 'never'
  return new Date(value).toLocaleString()
}

function capabilityAgent(agent: Agent) {
  const value = agent.capabilities?.agent
  if (typeof value === 'string') return value
  if (agent.name === 'silicon-cc') return 'scc'
  if (agent.agent_type === 'claude_code') return 'scc'
  return agent.agent_type
}

function displayAgentType(agentType: string) {
  if (agentType === 'claude_code') return 'scc'
  return agentType
}

function resolveGatewayWsUrl(url: string) {
  const gatewayBase = STREAMING_BASE.replace(/^http/, 'ws').replace(/\/$/, '')
  try {
    const parsed = new URL(url)
    return `${gatewayBase}${parsed.pathname}${parsed.search}`
  } catch {
    if (url.startsWith('/')) return `${gatewayBase}${url}`
    return url
  }
}

function performanceLevel(agentCount: number, cores: number) {
  const ratio = agentCount / Math.max(1, cores)
  if (ratio <= 2) return { level: 'green', label: '轻载' }
  if (ratio <= 3) return { level: 'yellow', label: '中载' }
  return { level: 'red', label: '重载' }
}

function clampScale(value: number) {
  return Math.min(2, Math.max(0.25, Number(value.toFixed(2))))
}

function seatColorFor(agentType: string, role: SessionRole) {
  if (role === 'leader') return 'rgba(203, 213, 225, 0.06)'
  const colors: Record<string, string> = {
    reasonix: 'rgba(148, 163, 184, 0.06)',
    codex: 'rgba(251, 191, 36, 0.04)',
    claude: 'rgba(249, 115, 22, 0.04)',
    claude_code: 'rgba(34, 197, 94, 0.04)',
    scc: 'rgba(34, 197, 94, 0.04)',
    hermes: 'rgba(59, 130, 246, 0.04)',
    leader: 'rgba(203, 213, 225, 0.06)',
  }
  return colors[agentType] ?? 'rgba(148, 163, 184, 0.03)'
}

interface AppProps {
  gatewayToken?: string
  onAuthError?: () => void
}

function App({ gatewayToken, onAuthError }: AppProps = {}) {
  const gApi = useCallback(<T,>(path: string, init?: RequestInit) =>
    streamingApi<T>(path, init, gatewayToken, onAuthError), [gatewayToken, onAuthError])
  const [tasks, setTasks] = useState<Task[]>([])
  const [agents, setAgents] = useState<Agent[]>([])
  const [events, setEvents] = useState<EventItem[]>([])
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null)
  const [streamEvents, setStreamEvents] = useState<Record<string, AgentStreamEvent[]>>({})
  const [showCreate, setShowCreate] = useState(false)
  const [agentTemplate, setAgentTemplate] = useState<AgentTemplate | null>(null)
  const [agentName, setAgentName] = useState('')
  const [form, setForm] = useState<CreateTaskForm>(emptyForm)
  const [showBroadcast, setShowBroadcast] = useState(false)
  const [broadcastForm, setBroadcastForm] = useState<BroadcastForm>(emptyBroadcast)
  const [gatewayHealth, setGatewayHealth] = useState<GatewayHealth | null>(null)
  const [machines, setMachines] = useState<DormMachine[]>([])
  const [agentWindows, setAgentWindows] = useState<AgentWindowState[]>([])
  const [focusedWindowId, setFocusedWindowId] = useState<string | null>(null)
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null)
  const [lastChatMessage, setLastChatMessage] = useState('')
  const [stages, setStages] = useState<StageState[]>([])
  const [currentStage, setCurrentStage] = useState<StageName | null>(null)
  const [canvasScale, setCanvasScale] = useState(1)
  const [canvasOffset, setCanvasOffset] = useState({ x: 0, y: 0 })
  const panStartRef = useRef<{ x: number; y: number; offsetX: number; offsetY: number } | null>(null)
  const [layout, setLayout] = useState<LayoutConfig>({
    mode: "grid",
    sortBy: "status",
    groupBy: "none",
  })
  const [sessionEvents, setSessionEvents] = useState<Record<string, AgentStreamEvent[]>>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [pwaCacheControlled] = useState(() => Boolean(navigator.serviceWorker?.controller))

  const selectedTask = useMemo(
    () => tasks.find((task) => task.id === selectedTaskId) ?? null,
    [selectedTaskId, tasks],
  )

  const activeSession = useMemo(
    () => gatewayHealth?.sessions?.find((session) => session.session_id === activeSessionId) ?? null,
    [activeSessionId, gatewayHealth],
  )

  const localCores = useMemo(() => navigator.hardwareConcurrency || 4, [])
  const perf = useMemo(
    () => performanceLevel(agentWindows.length, localCores),
    [agentWindows.length, localCores],
  )
  const costGuardWarnings = useMemo(() => {
    return Object.entries(gatewayHealth?.cost_guard ?? {}).flatMap(([agentType, guard]) => {
      if (guard.max == null || guard.active <= guard.max) return []
      return [`${agentType} ${guard.active}/${guard.max}`]
    })
  }, [gatewayHealth])
  const sessionRecordEvents = useMemo<SessionRecordEvent[]>(() => {
    if (!activeSessionId) return []
    return (sessionEvents[activeSessionId] ?? []).map((event) => ({
      timestamp: event.timestamp,
      type: event.type,
      agentId: event.agent_id,
      content: streamLine(event),
    }))
  }, [activeSessionId, sessionEvents])
  const footerStats = useMemo(() => {
    const completedRounds = tasks.filter((task) => task.status === 'done').length
    const stalledRounds = tasks.filter((task) => task.status.startsWith('blocked')).length
    const currentRound = completedRounds + stalledRounds + tasks.filter((task) =>
      task.status === 'running' || task.status === 'leased',
    ).length
    const participantExpected = Math.max(
      activeSession?.participants.length ?? 0,
      agentWindows.length,
      gatewayHealth?.agents?.length ?? 0,
    )
    const participantPresent = Math.max(
      activeSession?.connections ?? 0,
      gatewayHealth?.agents?.filter((agent) => agent.status === 'online').length ?? 0,
      agentWindows.filter((window) => window.status !== 'left').length,
    )
    return {
      totalRounds: tasks.length,
      currentRound,
      completedRounds,
      stalledRounds,
      participantExpected,
      participantPresent,
      participantMissing: Math.max(0, participantExpected - participantPresent),
    }
  }, [activeSession, agentWindows, gatewayHealth, tasks])
  const activeRound = useMemo(() => {
    const stageRound = stages.find((stage) => stage.name === currentStage)?.round
    return Math.max(1, stageRound ?? footerStats.currentRound ?? 1)
  }, [currentStage, footerStats.currentRound, stages])
  const roundParticipants = useMemo(() => {
    const sessionParticipants = activeSession?.participants ?? []
    if (sessionParticipants.length) {
      return sessionParticipants.map((agentId) => {
        const agent = gatewayHealth?.agents?.find((item) => item.agent_id === agentId)
        return {
          name: agent?.agent_name ?? agentId,
          role: agent?.agent_type ?? 'participant',
          status: agent?.status ?? 'unknown',
        }
      })
    }
    return agentWindows.map((window) => ({
      name: window.agentName,
      role: window.role,
      status: window.status,
    }))
  }, [activeSession, agentWindows, gatewayHealth])

  const loadTasks = useCallback(async () => {
    const [taskRows, agentRows, gateway, machineRows] = await Promise.all([
      api<Task[]>('/tasks'),
      api<Agent[]>('/agents'),
      streamingApi<GatewayHealth>('/health').catch(() => null),
      streamingApi<DormMachine[]>('/machines').catch(() => []),
    ])
    setTasks(taskRows)
    setAgents(agentRows)
    setGatewayHealth(gateway)
    setMachines(machineRows)
  }, [])

  const refresh = useCallback(async () => {
    try {
      setError(null)
      await loadTasks()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }, [loadTasks])

  useSessionStage(setStages, setCurrentStage)

  useEffect(() => {
    const initial = window.setTimeout(() => void refresh(), 0)
    const timer = window.setInterval(() => void refresh(), 3000)
    console.info('[Canvas] STREAMING_BASE', STREAMING_BASE)
    return () => {
      window.clearTimeout(initial)
      window.clearInterval(timer)
    }
  }, [refresh])

  const resetPwaCache = useCallback(async () => {
    if (!('serviceWorker' in navigator)) return
    const registrations = await navigator.serviceWorker.getRegistrations()
    await Promise.all(registrations.map((registration) => registration.unregister()))
    window.location.reload()
  }, [])

  useEffect(() => {
    if (!selectedTaskId) {
      return
    }
    let cancelled = false
    const loadEvents = async () => {
      try {
        const rows = await api<EventItem[]>(`/events?task_id=${selectedTaskId}`)
        if (!cancelled) setEvents(rows)
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      }
    }
    void loadEvents()
    const timer = window.setInterval(loadEvents, 3000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [selectedTaskId])

  useEffect(() => {
    if (!selectedTask) return
    const sessionId = selectedTask.id
    const source = new EventSource(`${STREAMING_BASE}/stream/sessions/${sessionId}`)
    source.addEventListener('agent_output', (message) => {
      try {
        const event = JSON.parse((message as MessageEvent).data) as AgentStreamEvent
        setStreamEvents((current) => ({
          ...current,
          [sessionId]: [...(current[sessionId] ?? []), event].slice(-200),
        }))
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err))
      }
    })
    source.onerror = () => {
      const warningEvent: AgentStreamEvent = {
        session_id: sessionId,
        msg_id: `local-${Date.now()}`,
        agent_id: 'canvas',
        type: 'warning',
        payload: { message: 'stream disconnected; browser will retry' },
        timestamp: new Date().toISOString(),
      }
      setStreamEvents((current) => ({
        ...current,
        [sessionId]: [
          ...(current[sessionId] ?? []),
          warningEvent,
        ].slice(-200),
      }))
    }
    return () => source.close()
  }, [selectedTask])

  useEffect(() => {
    if (!activeSessionId) return
    const source = new EventSource(`${STREAMING_BASE}/stream/sessions/${activeSessionId}`)
    source.addEventListener('agent_output', (message) => {
      try {
        const event = JSON.parse((message as MessageEvent).data) as AgentStreamEvent
        setSessionEvents((current) => ({
          ...current,
          [activeSessionId]: [...(current[activeSessionId] ?? []), event].slice(-300),
        }))
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err))
      }
    })
    return () => source.close()
  }, [activeSessionId])

  const onCreate = async () => {
    setSaving(true)
    setError(null)
    try {
      const requiredCapabilities = parseJsonField(form.required_capabilities, {})
      const acceptanceCheck = parseJsonField(form.acceptance_check, { type: 'manual' })
      const task = await api<Task>('/tasks', {
        method: 'POST',
        body: JSON.stringify({
          title: form.title,
          description: form.description,
          task_type: form.task_type,
          priority: 100,
          max_attempts: 3,
          dependencies: [],
          required_capabilities: requiredCapabilities,
          acceptance_check: acceptanceCheck,
          payload: {
            instruction: form.instruction,
            context: { mode: 'inline' },
          },
          created_by: 'canvas',
        }),
      })
      setSelectedTaskId(task.id)
      setShowCreate(false)
      setForm(emptyForm)
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setSaving(false)
    }
  }

  const openAgentTemplate = (template: AgentTemplate) => {
    setAgentTemplate(template)
    setAgentName(template.defaultName)
  }

  const registerTemplateAgent = async () => {
    if (!agentTemplate) return
    setSaving(true)
    setError(null)
    try {
      await api('/agents/register', {
        method: 'POST',
        body: JSON.stringify({
          name: agentName,
          agent_type: agentTemplate.agent_type,
          host_id: agentName,
          os: 'unknown',
          max_concurrency: 1,
          capabilities: agentTemplate.capabilities,
        }),
      })
      setAgentTemplate(null)
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setSaving(false)
    }
  }

  const toggleBroadcastAgent = (agentId: string) => {
    setBroadcastForm((current) => ({
      ...current,
      selectedAgentIds: current.selectedAgentIds.includes(agentId)
        ? current.selectedAgentIds.filter((id) => id !== agentId)
        : [...current.selectedAgentIds, agentId],
    }))
  }

  const sendBroadcast = async () => {
    setSaving(true)
    setError(null)
    try {
      const selectedAgents = agents.filter((agent) =>
        broadcastForm.selectedAgentIds.includes(agent.id),
      )
      const requiredNames = selectedAgents.map((agent) => agent.name)
      const response = await streamingApi<{ session_id: string }>('/sessions/invite', {
        method: 'POST',
        body: JSON.stringify({
          goal: broadcastForm.goal,
          invite: {
            capabilities: {},
            required_names: requiredNames,
            preferred_names: requiredNames,
            min_count: Math.max(1, requiredNames.length),
            role: 'participant',
          },
          cost_policy: {
            max_active_by_agent_type: {
              codex: broadcastForm.maxCodex,
              scc: broadcastForm.maxScc,
              reasonix: broadcastForm.maxReasonix,
              hermes: broadcastForm.maxHermes,
            },
          },
          stage: '论证',
          stage_round: 1,
          max_rounds: 2,
        }),
      })
      setActiveSessionId(response.session_id)
      setShowBroadcast(false)
      setBroadcastForm(emptyBroadcast)
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setSaving(false)
    }
  }

  const finishSession = async () => {
    if (!activeSessionId) return
    setSaving(true)
    setError(null)
    try {
      const message = {
        type: 'session_done',
        outcome: 'success',
        summary: 'Session closed from Canvas.',
      }
      await gApi(`/sessions/${activeSessionId}/message`, {
        method: 'POST',
        body: JSON.stringify(message),
      })
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setSaving(false)
    }
  }

  const postSessionMessage = useCallback(async (body: Record<string, unknown>) => {
    if (!activeSessionId) {
      throw new Error('No active Gateway session.')
    }
    await streamingApi(`/sessions/${activeSessionId}/message`, {
      method: 'POST',
      body: JSON.stringify(body),
    })
  }, [activeSessionId])

  const handleNewRound = useCallback(async (instruction: string) => {
    const nextRound = activeRound + 1
    setLastChatMessage(instruction)
    await postSessionMessage({
      type: 'round_instruction',
      message: instruction,
      payload: { stage: currentStage ?? '论证', stage_round: nextRound, status: 'active' },
      round: nextRound,
    })
    await refresh()
  }, [activeRound, currentStage, postSessionMessage, refresh])

  const handleCloseRound = useCallback(async () => {
    await postSessionMessage({
      type: 'round_closed',
      payload: { stage: currentStage ?? '论证', stage_round: activeRound, status: 'done' },
      round: activeRound,
    })
    await refresh()
  }, [activeRound, currentStage, postSessionMessage, refresh])

  const handleLeaderSubmit = useCallback(async (
    _windowId: string,
    kind: 'audit' | 'deployment' | 'decision',
    value: string,
  ) => {
    const body =
      kind === 'audit'
        ? { type: 'leader_audit', audit_opinion: value, round: activeRound }
        : kind === 'deployment'
          ? { type: 'leader_deployment', deployment_opinion: value, round: activeRound }
          : { type: 'round_decision', decision: value, round: activeRound }
    await postSessionMessage(body)
    await refresh()
  }, [activeRound, postSessionMessage, refresh])

  const focusWindow = useCallback((id: string) => {
    setAgentWindows((current) => {
      const nextZ = Math.max(1, ...current.map((item) => item.z)) + 1
      return current.map((item) => item.id === id ? { ...item, z: nextZ } : item)
    })
    setFocusedWindowId(id)
  }, [])

  const patchWindow = useCallback((id: string, patch: Partial<AgentWindowState>) => {
    setAgentWindows((current) =>
      current.map((item) => item.id === id ? { ...item, ...patch } : item),
    )
  }, [])

  const minimizeWindow = useCallback((id: string) => {
    patchWindow(id, { minimized: true })
  }, [patchWindow])

  const restoreWindow = useCallback((id: string) => {
    patchWindow(id, { minimized: false })
  }, [patchWindow])

  const closeWindow = useCallback((id: string) => {
    setAgentWindows((current) => current.filter((item) => item.id !== id))
    setFocusedWindowId((current) => current === id ? null : current)
  }, [])

  const ensureGatewaySession = useCallback(async () => {
    if (activeSessionId) return activeSessionId
    const response = await streamingApi<GatewaySessionCreateResponse>('/sessions', {
      method: 'POST',
      body: JSON.stringify({
        agent_name: 'canvas',
        agent_type: 'leader',
        tools: ['agent_window', 'dorm_sidebar'],
      }),
    })
    setActiveSessionId(response.session_id)
    return response.session_id
  }, [activeSessionId])

  const summonDormAgent = useCallback(async (
    machine: DormMachine,
    agent: DormAgent,
    role: SessionRole,
  ) => {
    setSaving(true)
    setError(null)
    try {
      const sessionId = await ensureGatewaySession()
      const response = await streamingApi<ParticipantCreateResponse>(`/sessions/${sessionId}/participants`, {
        method: 'POST',
        body: JSON.stringify({
          machine_id: machine.machineId,
          agent_template_id: agent.agentTemplateId,
          role,
          mode: 'pty',
          initial_context: {
            stage: 'standby',
            goal: 'Canvas AgentWindow summoned from DormSidebar.',
          },
        }),
      })
      const index = agentWindows.length
      const id = response.participant_id
      const newWindow: AgentWindowState = {
        id,
        participantId: response.participant_id,
        terminalId: response.terminal_id,
        agentId: `${machine.machineId}:${agent.agentTemplateId}`,
        agentName: agent.agentName,
        agentType: agent.agentType,
        machineName: machine.displayName,
        role,
        status: 'summoned',
        wsUrl: resolveGatewayWsUrl(response.pty_ws_url),
        x: 24 + (index % 2) * 430,
        y: 24 + Math.floor(index / 2) * 300,
        width: 480,
        height: 520,
        z: 10 + index,
        minimized: false,
        seatColor: seatColorFor(agent.agentType, role),
        instruction: lastChatMessage || undefined,
      }
      setAgentWindows((current) => [...current, newWindow])
      setFocusedWindowId(id)
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setSaving(false)
    }
  }, [agentWindows.length, ensureGatewaySession, lastChatMessage, refresh])

  const handleChatSend = useCallback(async (message: string) => {
    setSaving(true)
    setError(null)
    try {
      setLastChatMessage(message)
      const response = await streamingApi<GatewaySessionCreateResponse>('/sessions', {
        method: 'POST',
        body: JSON.stringify({ agent_name: 'canvas', agent_type: 'leader' }),
      })
      setActiveSessionId(response.session_id)
      const health = await streamingApi<GatewayHealth>('/health')
      setGatewayHealth(health)
      const onlineAgents = (health.agents ?? []).filter((agent) => agent.status === 'online_idle')
      if (onlineAgents.length > 0) {
        await gApi(`/sessions/${response.session_id}/invite`, {
          method: 'POST',
          body: JSON.stringify({
            goal: message,
            invite: {
              capabilities: {},
              min_count: Math.min(onlineAgents.length, 2),
            },
            cost_policy: {
              max_active_by_agent_type: { reasonix: 2, codex: 1, scc: 1 },
            },
            stage: '论证',
            stage_round: 1,
            max_rounds: 2,
          }),
        })
      }
      await gApi(`/sessions/${response.session_id}/message`, {
        method: 'POST',
        body: JSON.stringify({
          type: 'session_message',
          message,
          payload: { stage: '论证', stage_round: 1 },
        }),
      })
      await refresh()
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      console.error('[Canvas] ChatInput send failed', err)
      setError(message)
      throw err
    } finally {
      setSaving(false)
    }
  }, [refresh])

  const zoomCanvas = useCallback((delta: number) => {
    setCanvasScale((scale) => clampScale(scale + delta))
  }, [])

  const fitCanvas = useCallback(() => {
    setCanvasScale(1)
    setCanvasOffset({ x: 0, y: 0 })
  }, [])

  const handleCanvasWheel = useCallback((event: WheelEvent<HTMLDivElement>) => {
    if (!event.ctrlKey) return
    event.preventDefault()
    const direction = event.deltaY > 0 ? -0.08 : 0.08
    setCanvasScale((scale) => clampScale(scale + direction))
  }, [])

  const handleCanvasMouseDown = useCallback((event: ReactMouseEvent<HTMLDivElement>) => {
    if (event.button !== 0) return
    const target = event.target as HTMLElement
    if (target.closest('.agent-window, .agent-taskbar, .layout-toolbar, .zoom-toolbar, .chat-input-bar, .react-flow, .stage-pipeline-wrapper')) {
      return
    }
    event.preventDefault()
    panStartRef.current = {
      x: event.clientX,
      y: event.clientY,
      offsetX: canvasOffset.x,
      offsetY: canvasOffset.y,
    }
    const move = (moveEvent: MouseEvent) => {
      const start = panStartRef.current
      if (!start) return
      setCanvasOffset({
        x: start.offsetX + moveEvent.clientX - start.x,
        y: start.offsetY + moveEvent.clientY - start.y,
      })
    }
    const up = () => {
      panStartRef.current = null
      document.removeEventListener('mousemove', move)
      document.removeEventListener('mouseup', up)
    }
    document.addEventListener('mousemove', move)
    document.addEventListener('mouseup', up)
  }, [canvasOffset])

  const publishMockStream = async () => {
    if (!selectedTask) return
    const sessionId = selectedTask.id
    const event: AgentStreamEvent = {
      session_id: sessionId,
      msg_id: crypto.randomUUID(),
      agent_id: selectedTask.lease_owner ?? 'mock-agent',
      type: 'text',
      payload: { content: `mock stream ${new Date().toLocaleTimeString()}` },
      timestamp: new Date().toISOString(),
    }
    try {
      await gApi(`/sessions/${sessionId}/events`, {
        method: 'POST',
        body: JSON.stringify(event),
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <GitBranch size={22} />
          <div>
            <h1>UnionAgents</h1>
            <span>Phase 2 Canvas</span>
          </div>
        </div>

        <section>
          <div className="section-title">
            <h2>Tasks</h2>
            <span style={{ fontSize: 11, color: '#64748b' }}>
              {tasks.filter((t) => !['done', 'cancelled'].includes(t.status)).length} active
            </span>
          </div>
          <div className="task-queue">
            {tasks
              .filter((t) => !['done', 'cancelled'].includes(t.status))
              .sort((a, b) => b.priority - a.priority)
              .slice(0, 25)
              .map((t) => (
                <button
                  key={t.id}
                  className={`task-queue-row ${selectedTaskId === t.id ? 'selected' : ''}`}
                  onClick={() => setSelectedTaskId(t.id)}
                >
                  <span
                    className="task-queue-dot"
                    style={{ background: statusColor[t.status] ?? '#64748b' }}
                  />
                  <span className="task-queue-title">{t.title}</span>
                  <span className="task-queue-prio">p{t.priority}</span>
                </button>
              ))}
            {tasks.filter((t) => !['done', 'cancelled'].includes(t.status)).length === 0 && (
              <span style={{ fontSize: 11, color: '#475569', padding: '4px 0' }}>All clear</span>
            )}
          </div>
        </section>

        <button className="primary-button" onClick={() => setShowCreate(true)}>
          <CirclePlus size={18} />
          New task
        </button>
        <button className="primary-button broadcast-button" onClick={() => setShowBroadcast(true)}>
          <Megaphone size={18} />
          Broadcast
        </button>

        <section>
          <h2>Task types</h2>
          <div className="palette">
            {taskTypes.map((type) => (
              <button
                key={type}
                draggable
                onDragStart={(event) => event.dataTransfer.setData('task-type', type)}
                onClick={() => {
                  setForm({ ...emptyForm, task_type: type })
                  setShowCreate(true)
                }}
              >
                {type}
              </button>
            ))}
          </div>
        </section>

        <DormSidebar
          machines={machines}
          disabled={saving}
          onSummon={(machine, agent, role) => {
            void summonDormAgent(machine, agent, role)
          }}
        />

        <section>
          <div className="section-title">
            <h2>Agent templates</h2>
            <Play size={16} />
          </div>
          <div className="palette">
            {agentTemplates.map((template) => (
              <button
                key={template.label}
                draggable
                onDragStart={(event) =>
                  event.dataTransfer.setData('agent-template', template.label)
                }
                onClick={() => openAgentTemplate(template)}
              >
                {template.label}
              </button>
            ))}
          </div>
        </section>

        <section>
          <div className="section-title">
            <h2>Agents</h2>
            <Bot size={16} />
          </div>
          <div className="agent-list">
            {agents.map((agent) => (
              <div key={agent.id} className="agent-row">
                <span
                  className={`agent-light ${agent.status === 'online' ? 'online' : 'offline'}`}
                />
                <div>
                  <strong>{agent.name}</strong>
                  <small>
                    {displayAgentType(capabilityAgent(agent))} / {agent.os}
                  </small>
                </div>
              </div>
            ))}
          </div>
        </section>
      </aside>

      <section className="canvas-panel">
        <header className="topbar">
          <div>
            <strong>{tasks.length} tasks</strong>
            <span>{API_BASE}</span>
            <span>{STREAMING_BASE}</span>
          </div>
          <div className="topbar-actions">
            <div className={`performance-pill ${perf.level}`}>
              <span className={`performance-dot ${perf.level}`} />
              <strong>与会 {agentWindows.length} Agent</strong>
              <span>本机 {perf.label} ({localCores}核)</span>
            </div>
            <div className="cost-guard">
              <ShieldCheck size={15} />
              <span>Codex {gatewayHealth?.cost_guard?.codex?.active ?? 0}/1</span>
              <span>SCC {gatewayHealth?.cost_guard?.scc?.active ?? 0}/1</span>
              <span>Reasonix {gatewayHealth?.cost_guard?.reasonix?.active ?? 0}/2</span>
            </div>
            {pwaCacheControlled && (
              <button className="ghost-button" onClick={() => void resetPwaCache()}>
                Clear SW
              </button>
            )}
            <button className="ghost-button" onClick={() => void refresh()}>
              {loading ? <Loader2 className="spin" size={16} /> : <RefreshCw size={16} />}
              Refresh
            </button>
          </div>
        </header>

        {error && (
          <div className="error-banner">
            <AlertTriangle size={18} />
            <span>{error}</span>
            <button onClick={() => setError(null)}>
              <X size={16} />
            </button>
          </div>
        )}

        <div
          className="flow-wrap"
          onWheel={handleCanvasWheel}
          onMouseDown={handleCanvasMouseDown}
          onDrop={(event) => {
            event.preventDefault()
            const type = event.dataTransfer.getData('task-type')
            const agentLabel = event.dataTransfer.getData('agent-template')
            if (type) {
              setForm({ ...emptyForm, task_type: type })
              setShowCreate(true)
            }
            if (agentLabel) {
              const template = agentTemplates.find((item) => item.label === agentLabel)
              if (template) openAgentTemplate(template)
            }
          }}
          onDragOver={(event) => event.preventDefault()}
        >
          <div className="zoom-toolbar">
            <button title="Zoom out" onClick={() => zoomCanvas(-0.1)}>
              <ZoomOut size={15} />
            </button>
            <button title="Zoom in" onClick={() => zoomCanvas(0.1)}>
              <ZoomIn size={15} />
            </button>
            <button title="Reset zoom" onClick={() => setCanvasScale(1)}>
              <LocateFixed size={15} />
              <span>{Math.round(canvasScale * 100)}%</span>
            </button>
            <button title="Fit workspace" onClick={fitCanvas}>
              <Minus size={15} />
              <Plus size={15} />
              <span>Fit</span>
            </button>
          </div>
          <div
            className="canvas-viewport"
            style={{
              transform: `translate(${canvasOffset.x}px, ${canvasOffset.y}px)`,
            }}
          >
            <div
              className="canvas-workspace"
              style={{
                transform: `scale(${canvasScale})`,
              }}
            >
              <LayoutToolbar config={layout} onChange={setLayout} />
              <StagePipeline stages={stages} currentStage={currentStage} />
              <RoundPanel
                sessionId={activeSessionId}
                currentRound={activeRound}
                maxRounds={stages.find((stage) => stage.name === currentStage)?.maxRounds ?? 2}
                leaderInstruction={lastChatMessage}
                participants={roundParticipants}
                onNewRound={handleNewRound}
                onCloseRound={handleCloseRound}
              />
              <WindowManager
                windows={agentWindows}
                focusedId={focusedWindowId}
                sessionId={activeSessionId}
                currentRound={activeRound}
                onFocus={focusWindow}
                onPatch={patchWindow}
                onMinimize={minimizeWindow}
                onRestore={restoreWindow}
                onClose={closeWindow}
                onLeaderSubmit={handleLeaderSubmit}
              />
            </div>
          </div>
          <ChatInput onSend={handleChatSend} disabled={saving} />
        </div>
      </section>

      <StatusFooter
        totalRounds={footerStats.totalRounds}
        currentRound={footerStats.currentRound}
        completedRounds={footerStats.completedRounds}
        stalledRounds={footerStats.stalledRounds}
        participantExpected={footerStats.participantExpected}
        participantPresent={footerStats.participantPresent}
        participantMissing={footerStats.participantMissing}
        activeAgents={footerStats.participantPresent}
        costGuardWarnings={costGuardWarnings}
      />

      <aside className="right-rail">
        <SessionRecord
          sessionId={activeSessionId}
          events={sessionRecordEvents}
        />
        <section className={`drawer ${selectedTask || activeSessionId ? 'open' : ''}`}>
        {activeSessionId ? (
          <>
            <button className="close-button" onClick={() => setActiveSessionId(null)}>
              <X size={18} />
            </button>
            <div className="drawer-head">
              <span className="status-pill session-status">
                {activeSession?.status ?? 'active'}
              </span>
              <h2>Session</h2>
              <p>{activeSessionId}</p>
            </div>

            <dl className="task-meta">
              <div>
                <dt>Participants</dt>
                <dd>{activeSession?.participants.length ?? 0}</dd>
              </div>
              <div>
                <dt>Connections</dt>
                <dd>{activeSession?.connections ?? 0}</dd>
              </div>
            </dl>

            <section className="drawer-section">
              <h3>Participants</h3>
              <div className="session-participants">
                {(activeSession?.participants ?? []).map((agentId) => {
                  const agent = gatewayHealth?.agents?.find((item) => item.agent_id === agentId)
                  return (
                    <div key={agentId} className="session-participant">
                      <strong>{agent?.agent_name ?? agentId}</strong>
                      <small>{agent?.status ?? 'unknown'} / {agent?.agent_type ?? 'agent'}</small>
                    </div>
                  )
                })}
                {!(activeSession?.participants ?? []).length && <span>No participants yet</span>}
              </div>
            </section>

            <section className="drawer-section">
              <div className="terminal-actions">
                <h3>Session Stream</h3>
                <button className="ghost-button" disabled={saving} onClick={() => void finishSession()}>
                  <Square size={14} />
                  End
                </button>
              </div>
              <TerminalPanel
                key={activeSessionId}
                sessionId={activeSessionId}
                events={sessionEvents[activeSessionId] ?? []}
              />
            </section>

            <section className="drawer-section">
              <h3>Timeline</h3>
              <div className="event-list">
                {(sessionEvents[activeSessionId] ?? []).slice(-20).reverse().map((event) => (
                  <div key={event.msg_id} className="event-row info">
                    <Activity size={14} />
                    <div>
                      <strong>{String(event.payload.event_type ?? event.type)}</strong>
                      <span>{streamLine(event)}</span>
                      <small>{formatTime(event.timestamp)}</small>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          </>
        ) : selectedTask ? (
          <>
            <button className="close-button" onClick={() => setSelectedTaskId(null)}>
              <X size={18} />
            </button>
            <div className="drawer-head">
              <span
                className="status-pill"
                style={{ background: statusColor[selectedTask.status] ?? '#64748b' }}
              >
                {selectedTask.status}
              </span>
              <h2>{selectedTask.title}</h2>
              <p>{selectedTask.description || 'No description'}</p>
            </div>

            <dl className="task-meta">
              <div>
                <dt>Type</dt>
                <dd>{selectedTask.task_type}</dd>
              </div>
              <div>
                <dt>Priority</dt>
                <dd>{selectedTask.priority}</dd>
              </div>
              <div>
                <dt>Dependencies</dt>
                <dd>{selectedTask.dependencies.length}</dd>
              </div>
              <div>
                <dt>Updated</dt>
                <dd>{formatTime(selectedTask.updated_at)}</dd>
              </div>
            </dl>

            <section className="drawer-section">
              <div className="terminal-actions">
                <h3>Agent Stream</h3>
                <button className="ghost-button" onClick={() => void publishMockStream()}>
                  <Play size={14} />
                  Mock
                </button>
                <button className="ghost-button" disabled>
                  <Square size={14} />
                  Stop
                </button>
              </div>
              <TerminalPanel
                key={selectedTask.id}
                sessionId={selectedTask.id}
                events={streamEvents[selectedTask.id] ?? []}
              />
            </section>

            <section className="drawer-section">
              <h3>Payload</h3>
              <pre>{JSON.stringify(selectedTask.payload, null, 2)}</pre>
            </section>

            <section className="drawer-section">
              <h3>Acceptance</h3>
              <pre>{JSON.stringify(selectedTask.acceptance_check, null, 2)}</pre>
            </section>

            <section className="drawer-section">
              <h3>Events</h3>
              <div className="event-list">
                {events.map((event) => (
                  <div key={event.id} className={`event-row ${event.level}`}>
                    <Activity size={14} />
                    <div>
                      <strong>{event.event_type}</strong>
                      <span>{event.message}</span>
                      <small>{formatTime(event.created_at)}</small>
                    </div>
                  </div>
                ))}
                {!events.length && (
                  <div className="empty-events">
                    <Clock3 size={16} />
                    No events yet
                  </div>
                )}
              </div>
            </section>

            <section className="drawer-section">
              <h3>Artifacts</h3>
              <TaskPanel taskId={selectedTask.id} />
            </section>
          </>
        ) : (
          <div className="drawer-empty">
            <CheckCircle2 size={28} />
            <span>Select a task</span>
          </div>
        )}
        </section>
      </aside>

      <StatusFooter
        totalRounds={footerStats.totalRounds}
        currentRound={footerStats.currentRound}
        completedRounds={footerStats.completedRounds}
        stalledRounds={footerStats.stalledRounds}
        participantExpected={footerStats.participantExpected}
        participantPresent={footerStats.participantPresent}
        participantMissing={footerStats.participantMissing}
        activeAgents={agentWindows.length}
        costGuardWarnings={costGuardWarnings}
      />

      {showCreate && (
        <div className="modal-backdrop">
          <div className="modal">
            <div className="modal-head">
              <h2>Create task</h2>
              <button onClick={() => setShowCreate(false)}>
                <X size={18} />
              </button>
            </div>
            <label>
              Title
              <input
                value={form.title}
                onChange={(event) => setForm((current) => ({ ...current, title: event.target.value }))}
              />
            </label>
            <label>
              Type
              <select
                value={form.task_type}
                onChange={(event) =>
                  setForm((current) => ({ ...current, task_type: event.target.value }))
                }
              >
                {taskTypes.map((type) => (
                  <option key={type}>{type}</option>
                ))}
              </select>
            </label>
            <label>
              Description
              <textarea
                rows={2}
                value={form.description}
                onChange={(event) =>
                  setForm((current) => ({ ...current, description: event.target.value }))
                }
              />
            </label>
            <label>
              Instruction
              <textarea
                rows={5}
                value={form.instruction}
                onChange={(event) =>
                  setForm((current) => ({ ...current, instruction: event.target.value }))
                }
              />
            </label>
            <div className="form-grid">
              <label>
                Required capabilities JSON
                <textarea
                  rows={5}
                  value={form.required_capabilities}
                  onChange={(event) =>
                    setForm((current) => ({
                      ...current,
                      required_capabilities: event.target.value,
                    }))
                  }
                />
              </label>
              <label>
                Acceptance check JSON
                <textarea
                  rows={5}
                  value={form.acceptance_check}
                  onChange={(event) =>
                    setForm((current) => ({ ...current, acceptance_check: event.target.value }))
                  }
                />
              </label>
            </div>
            <button
              className="primary-button"
              disabled={saving || !form.title.trim() || !form.instruction.trim()}
              onClick={() => void onCreate()}
            >
              {saving ? <Loader2 className="spin" size={16} /> : <CirclePlus size={16} />}
              Create
            </button>
          </div>
        </div>
      )}

      {showBroadcast && (
        <div className="modal-backdrop">
          <div className="modal">
            <div className="modal-head">
              <h2>Broadcast session</h2>
              <button onClick={() => setShowBroadcast(false)}>
                <X size={18} />
              </button>
            </div>
            <label>
              Goal
              <textarea
                rows={4}
                value={broadcastForm.goal}
                onChange={(event) =>
                  setBroadcastForm((current) => ({ ...current, goal: event.target.value }))
                }
              />
            </label>
            <section className="drawer-section">
              <h3>Invite agents</h3>
              <div className="broadcast-agent-grid">
                {agents.map((agent) => (
                  <label key={agent.id} className="broadcast-agent">
                    <input
                      type="checkbox"
                      checked={broadcastForm.selectedAgentIds.includes(agent.id)}
                      onChange={() => toggleBroadcastAgent(agent.id)}
                    />
                    <span>
                      <strong>{agent.name}</strong>
                      <small>{displayAgentType(capabilityAgent(agent))}</small>
                    </span>
                  </label>
                ))}
              </div>
            </section>
            <section className="drawer-section">
              <h3>Cost Guard</h3>
              <div className="form-grid">
                <label>
                  Codex max
                  <input
                    type="number"
                    min={0}
                    value={broadcastForm.maxCodex}
                    onChange={(event) =>
                      setBroadcastForm((current) => ({
                        ...current,
                        maxCodex: Number(event.target.value),
                      }))
                    }
                  />
                </label>
                <label>
                  SCC max
                  <input
                    type="number"
                    min={0}
                    value={broadcastForm.maxScc}
                    onChange={(event) =>
                      setBroadcastForm((current) => ({
                        ...current,
                        maxScc: Number(event.target.value),
                      }))
                    }
                  />
                </label>
                <label>
                  Reasonix max
                  <input
                    type="number"
                    min={0}
                    value={broadcastForm.maxReasonix}
                    onChange={(event) =>
                      setBroadcastForm((current) => ({
                        ...current,
                        maxReasonix: Number(event.target.value),
                      }))
                    }
                  />
                </label>
                <label>
                  Hermes max
                  <input
                    type="number"
                    min={0}
                    value={broadcastForm.maxHermes}
                    onChange={(event) =>
                      setBroadcastForm((current) => ({
                        ...current,
                        maxHermes: Number(event.target.value),
                      }))
                    }
                  />
                </label>
              </div>
            </section>
            {activeSessionId && (
              <div className="session-result">
                Active session: <strong>{activeSessionId}</strong>
              </div>
            )}
            <button
              className="primary-button"
              disabled={
                saving ||
                !broadcastForm.goal.trim() ||
                broadcastForm.selectedAgentIds.length === 0
              }
              onClick={() => void sendBroadcast()}
            >
              {saving ? <Loader2 className="spin" size={16} /> : <Megaphone size={16} />}
              Send broadcast
            </button>
          </div>
        </div>
      )}

      {agentTemplate && (
        <div className="modal-backdrop">
          <div className="modal small-modal">
            <div className="modal-head">
              <h2>Register agent</h2>
              <button onClick={() => setAgentTemplate(null)}>
                <X size={18} />
              </button>
            </div>
            <label>
              Agent name
              <input
                value={agentName}
                onChange={(event) => setAgentName(event.target.value)}
              />
            </label>
            <dl className="task-meta">
              <div>
                <dt>Type</dt>
                <dd>{agentTemplate.agent_type}</dd>
              </div>
              <div>
                <dt>Concurrency</dt>
                <dd>1</dd>
              </div>
            </dl>
            <section className="drawer-section">
              <h3>Capabilities</h3>
              <pre>{JSON.stringify(agentTemplate.capabilities, null, 2)}</pre>
            </section>
            <button
              className="primary-button"
              disabled={saving || !agentName.trim()}
              onClick={() => void registerTemplateAgent()}
            >
              {saving ? <Loader2 className="spin" size={16} /> : <Play size={16} />}
              Register
            </button>
          </div>
        </div>
      )}
    </main>
  )
}

export default App
