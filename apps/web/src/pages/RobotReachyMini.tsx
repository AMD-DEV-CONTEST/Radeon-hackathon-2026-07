import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import {
  ArrowLeft,
  Bot,
  Circle,
  Loader2,
  Monitor,
  Play,
  Power,
  RotateCcw,
} from 'lucide-react'
import { Button } from '../components/ui/button'
import { Badge } from '../components/ui/badge'
import { ReachyMotionEditor } from '../components/reachy/ReachyMotionEditor'
// M26 — UX 重构：主控页改用 Stage + SidebarTabs + 3 Tab + 高级抽屉
import { ReachyStage } from '../components/reachy/ReachyStage'
import { ReachySidebarTabs, type ReachyTab } from '../components/reachy/ReachySidebarTabs'
import { ReachyChatTab } from '../components/reachy/ReachyChatTab'
import { ReachyMotionTab } from '../components/reachy/ReachyMotionTab'
import { ReachyVisionTab } from '../components/reachy/ReachyVisionTab'
import { ReachyAdvancedDrawer } from '../components/reachy/ReachyAdvancedDrawer'
import { ReachyOnboardingCard } from '../components/reachy/ReachyOnboardingCard'
import {
  deleteReachyMove,
  getLocalCategories,
  getLocalMoves,
  getMotorStatus,
  getReachyMoveJson,
  getReachyPing,
  discardReachyRecord,
  resumeReachyRecordCapture,
  getReachyRecordStatus,
  getReachyState,
  getReachyVirtualStatus,
  moveGoto,
  playLocalMove,
  probeRealtimeHealth,
  setMotorMode,
  setReachyVirtualActive,
  startReachyRecord,
  startReachyVirtual,
  stopMove,
  stopReachyRecord,
  stopReachyRecordCapture,
  stopReachyVirtual,
  playReachyRecordedMove,
  startReachyHeadTracker,
  type ReachyFullState,
  type ReachyLocalDaemonStatus,
  type ReachyMotorMode,
  type ReachyPingResponse,
  type ReachyRecordStatus,
  type ReachyVirtualStatus,
} from '../lib/reachyApi'
import {
  getRobotManifest,
  getRobotDependencies,
  getRobotStatus,
  provisionRobotDependencies,
  startRobotService,
  stopRobotService,
  type RobotDependenciesResponse,
  type RobotManifest,
} from '../lib/robotApi'
import { agentWsUrl, isLocalDev } from '../lib/localAgent'
import { ReachyMiniGuide } from '../components/onboarding/ReachyMiniGuide'
import {
  extractHeadRpyFromPose,
  headRpyToNamedJoints,
  mergePassiveJoints,
  namedJointsToUrdf,
} from '../lib/reachyVirtualPreview'
import {
  loadReachyKinematicsWasm,
  buildNeutralUrdfJoints,
  ensureReachyUrdfJoints,
} from '../lib/reachyKinematicsWasm'
import { registerCopilotActionHandler } from '../lib/copilotAgent'
import { CommunityResources } from '../components/features/CommunityResources'

type WsState = 'idle' | 'connecting' | 'connected' | 'disconnected' | 'error'
type ViewerMode = 'view' | 'compose'
type RecordPhase = 'idle' | 'prep' | 'recording' | 'naming'

interface PlaybackTimeline {
  name: string
  duration: number
  startedAt: number
}

interface ReachyStateMessage {
  type: 'reachy_state' | 'reachy_error' | string
  robot_id?: string
  timestamp?: number
  state?: ReachyFullState
  joints?: Record<string, number | undefined>
  named_joints?: Record<string, number | undefined>
  message?: string
  error?: string
}

const REACHY_MINI_JOINT_NAMES = [
  'body_rotation',
  'stewart_1', 'stewart_2', 'stewart_3',
  'stewart_4', 'stewart_5', 'stewart_6',
  'right_antenna', 'left_antenna',
] as const

/** SDK gravity-compensation mode requires Placo kinematics; default daemon uses AnalyticalKinematics. */
const GRAVITY_COMPENSATION_AVAILABLE = false

/** Ignore sub-milliradian encoder noise on body yaw in the 3D preview. */
const URDF_BODY_JOINT_DEADBAND_RAD = 0.004

const DEFAULT_MOVES: Record<string, string[]> = {
  dances: ['hello', 'nod', 'shake', 'wiggle'],
  emotions: ['calm', 'excited', 'happy', 'sad'],
  custom: [],
}

// M26 — formatValue / formatPoseValue were used by the old CompactPoseReadout
// helper that has been removed. The new ReachyStage does not need them.

/** M21 — Compact pill showing the currently running Reachy App name + status. */
export function RobotReachyMini() {
  const [searchParams] = useSearchParams()
  const guideParam = searchParams.get('guide')
  const guideAutoStart = guideParam === '1' || guideParam === 'virtual'
  const guidePresetMode = 'virtual' as const
  const [meta, setMeta] = useState<RobotManifest | null>(null)
  const [metaErr, setMetaErr] = useState<string | null>(null)
  const [wsState, setWsState] = useState<WsState>('idle')
  const [wsError, setWsError] = useState<string | null>(null)
  const [realtimeReachable, setRealtimeReachable] = useState<boolean | null>(null)
  const [proxyStatus, setProxyStatus] = useState<'checking' | 'ok' | '502' | 'offline'>('checking')
  const socketRef = useRef<WebSocket | null>(null)
  const wsReconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const wsReconnectAttempt = useRef(0)
  const refreshInFlight = useRef(false)
  const wsFrameRef = useRef<number | null>(null)
  const wsPendingRef = useRef<ReachyStateMessage | null>(null)
  const urdfBodyYawRef = useRef<number | null>(null)
  const [state, setState] = useState<ReachyFullState | null>(null)
  const [reachyPing, setReachyPing] = useState<ReachyPingResponse | null>(null)
  const [localDaemonStatus, setLocalDaemonStatus] = useState<ReachyLocalDaemonStatus | null>(null)
  const [dependencyStatus, setDependencyStatus] = useState<RobotDependenciesResponse | null>(null)
  const [daemonStatus, setDaemonStatus] = useState<string>('unknown')
  const [motorMode, setMotorModeState] = useState<string>('unknown')
  const [categories, setCategories] = useState<string[]>(Object.keys(DEFAULT_MOVES))
  const [selectedCategory, setSelectedCategory] = useState<string>('dances')
  const [moves, setMoves] = useState<string[]>(DEFAULT_MOVES.dances)
  const [selectedMove, setSelectedMove] = useState<string>('hello')
  const [currentMoveId, setCurrentMoveId] = useState<string | null>(null)
  const [playingMoveName, setPlayingMoveName] = useState<string | null>(null)
  const [namedJointsFromWs, setNamedJointsFromWs] = useState<Record<string, number>>({})
  const [neutralUrdfJoints, setNeutralUrdfJoints] = useState<Record<string, number>>({})
  const [numericJointsFromWs, setNumericJointsFromWs] = useState<Record<string, number>>({})
  const [actionBusy, setActionBusy] = useState<string | null>(null)
  const [actionMessage, setActionMessage] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [gotoTarget, setGotoTarget] = useState({
    roll: 0,
    pitch: 0,
    yaw: 0,
    bodyYaw: 0,
    duration: 1.0,
  })
  const [virtualStatus, setVirtualStatus] = useState<ReachyVirtualStatus | null>(null)
  const [recordStatus, setRecordStatus] = useState<ReachyRecordStatus | null>(null)
  const [viewerMode, setViewerMode] = useState<ViewerMode>('view')
  // M26 — UX 重构：主控页用 Stage + SidebarTabs，需要当前 Tab + 摄像头预览状态
  const [activeTab, setActiveTab] = useState<ReachyTab>('chat')
  const [cameraPreview, setCameraPreview] = useState<{
    on: boolean
    device: number
    url: string | null
  }>({ on: false, device: 0, url: null })
  const [editorCustomMoves, setEditorCustomMoves] = useState<string[]>([])
  const [recordConfirmOpen, setRecordConfirmOpen] = useState(false)
  const [recordPhase, setRecordPhase] = useState<RecordPhase>('idle')
  const [prepCountdown, setPrepCountdown] = useState(0)
  const [recordNamePromptOpen, setRecordNamePromptOpen] = useState(false)
  const [recordSaveName, setRecordSaveName] = useState('')
  const [recordFrozenElapsed, setRecordFrozenElapsed] = useState(0)
  const [recordStopping, setRecordStopping] = useState(false)
  const [playbackTimeline, setPlaybackTimeline] = useState<PlaybackTimeline | null>(null)
  const [playbackElapsed, setPlaybackElapsed] = useState(0)
  const [customManageOpen, setCustomManageOpen] = useState(false)
  const [customMoveList, setCustomMoveList] = useState<string[]>([])
  const prepTimerRef = useRef<number | null>(null)
  const displaySmoothRef = useRef<Record<string, number>>({})

  const checkRealtimeProxy = useCallback(async () => {
    const probe = await probeRealtimeHealth()
    if (probe.ok) {
      setProxyStatus('ok')
      return true
    }
    setProxyStatus(probe.status === 502 ? '502' : 'offline')
    setRealtimeReachable(false)
    return false
  }, [])

  useEffect(() => {
    void (async () => {
      const proxyOk = await checkRealtimeProxy()
      if (!proxyOk) return
      try {
        setMeta(await getRobotManifest('reachy_mini'))
        setRealtimeReachable(true)
        setMetaErr(null)
      } catch (e) {
        setMetaErr((e as Error).message)
        setRealtimeReachable(false)
      }
    })()
  }, [checkRealtimeProxy])

  const jointNames = useMemo(
    () => meta?.joint_names ?? [...REACHY_MINI_JOINT_NAMES],
    [meta],
  )

  const refreshSnapshot = async () => {
    if (refreshInFlight.current) return
    refreshInFlight.current = true
    try {
      const proxyOk = await checkRealtimeProxy()
      if (!proxyOk) {
        setMotorModeState('offline')
        setState(null)
        return
      }

      const [ping, localDaemon, deps, virtual] = await Promise.allSettled([
        getReachyPing(),
        getRobotStatus<ReachyLocalDaemonStatus>('reachy_mini'),
        getRobotDependencies('reachy_mini'),
        getReachyVirtualStatus(),
      ])

      const anySucceeded = [ping, localDaemon, deps, virtual].some((r) => r.status === 'fulfilled')
      const virtualActiveNow = virtual.status === 'fulfilled' && virtual.value.active
      setRealtimeReachable(anySucceeded || virtualActiveNow)

      if (!anySucceeded && !virtualActiveNow) {
        setMotorModeState('offline')
        setState(null)
        return
      }

      if (ping.status === 'fulfilled') {
        setReachyPing(ping.value)
        if (!ping.value.daemon_http.ok) {
          setDaemonStatus('offline')
        }
      }
      if (localDaemon.status === 'fulfilled') {
        setLocalDaemonStatus(localDaemon.value)
        setDaemonStatus(
          localDaemon.value.daemon_http.ok ? 'running' : 'offline',
        )
      }
      if (deps.status === 'fulfilled') {
        setDependencyStatus(deps.value)
      }
      if (virtual.status === 'fulfilled') {
        setVirtualStatus(virtual.value)
      }

      const daemonReadyNow = ping.status === 'fulfilled' && Boolean(ping.value.daemon_http.ok)
        || (localDaemon.status === 'fulfilled' && Boolean(localDaemon.value.daemon_http.ok))

      if (!daemonReadyNow && !virtualActiveNow) {
        setMotorModeState('offline')
        setState(null)
        return
      }

      const [motors, fullState] = await Promise.allSettled([
        getMotorStatus(),
        getReachyState(),
      ])

      if (motors.status === 'fulfilled') {
        setMotorModeState(String(motors.value.mode ?? 'unknown'))
      } else if (virtualActiveNow) {
        setMotorModeState(String(virtual.value?.motor_mode ?? 'disabled'))
      }
      if (fullState.status === 'fulfilled') {
        setState(fullState.value)
      }
    } finally {
      refreshInFlight.current = false
    }
  }

  useEffect(() => {
    void refreshSnapshot().catch((e) => setActionError((e as Error).message))
  }, [])

  useEffect(() => {
    void (async () => {
      try {
        const remoteCategories = await getLocalCategories()
        setRealtimeReachable(true)
        if (remoteCategories.length) {
          setCategories(remoteCategories)
          if (!remoteCategories.includes(selectedCategory)) {
            setSelectedCategory(remoteCategories[0])
          }
        }
      } catch {
        setCategories(Object.keys(DEFAULT_MOVES))
      }
    })()
  }, [])

  useEffect(() => {
    void (async () => {
      try {
        const remoteMoves = await getLocalMoves(selectedCategory)
        const nextMoves = remoteMoves.length
          ? remoteMoves
          : (DEFAULT_MOVES[selectedCategory] ?? [])
        setMoves(nextMoves)
        setSelectedMove((prev) => nextMoves.includes(prev) ? prev : (nextMoves[0] ?? ''))
      } catch {
        const fallbackMoves = DEFAULT_MOVES[selectedCategory] ?? []
        setMoves(fallbackMoves)
        setSelectedMove((prev) => fallbackMoves.includes(prev) ? prev : (fallbackMoves[0] ?? ''))
      }
    })()
  }, [selectedCategory])

  useEffect(() => {
    if (viewerMode !== 'compose') return
    void getLocalMoves('custom')
      .then(setEditorCustomMoves)
      .catch(() => setEditorCustomMoves([]))
  }, [viewerMode])

  const daemonOnline = Boolean(
    reachyPing?.daemon_http.ok
    || localDaemonStatus?.daemon_http.ok
    || daemonStatus === 'running'
    || daemonStatus === 'started'
    || daemonStatus === 'ok',
  )

  const virtualActive = Boolean(
    virtualStatus?.active
    || reachyPing?.virtual?.active,
  )

  // T1-1: 把虚拟模式状态同步到 reachyApi 模块，让后续 move/state/record 调用都走同源云端，
  // 避免被 localStorage 里残留的 Local Agent URL 劫持。
  useEffect(() => {
    setReachyVirtualActive(virtualActive)
    return () => {
      // 离开页面时复位，避免影响其他页面
      setReachyVirtualActive(false)
    }
  }, [virtualActive])

  // 没真机也能玩：?guide=virtual / ?play=1 自动开虚拟模式，并播一段 hello，不用先找按钮。
  const playParam = searchParams.get('play')
  const wantInstantPlay = guideParam === 'virtual' || playParam === '1'
  const instantPlayStarted = useRef(false)
  useEffect(() => {
    if (!wantInstantPlay || instantPlayStarted.current) return
    instantPlayStarted.current = true
    let cancelled = false
    void (async () => {
      try {
        setReachyVirtualActive(true)
        setActionBusy('virtual-start')
        setActionMessage('正在进入虚拟体验（无需硬件）…')
        const started = await startReachyVirtual()
        if (cancelled) return
        if (!started.active) throw new Error(started.message || '虚拟模式启动失败')
        const status = await getReachyVirtualStatus()
        if (cancelled) return
        setVirtualStatus(status)
        setActionMessage('虚拟模式已开 · 正在播放 hello…')
        setSelectedCategory('dances')
        setSelectedMove('hello')
        setPlayingMoveName('hello')
        const result = await playLocalMove('hello')
        if (cancelled) return
        setCurrentMoveId(typeof result.uuid === 'string' ? result.uuid : null)
        setActionMessage('这就是没真机时的玩法：看 3D、点动作、继续探索。')
      } catch (e) {
        if (!cancelled) {
          setActionError((e as Error).message || '虚拟体验启动失败，请点「虚拟模式」重试')
          instantPlayStarted.current = false
        }
      } finally {
        if (!cancelled) setActionBusy(null)
      }
    })()
    return () => {
      cancelled = true
    }
    // 仅在进入带 play/guide 参数时跑一次
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wantInstantPlay])

  const reachyReady = daemonOnline || virtualActive
  const isRecording = Boolean(recordStatus?.active || reachyPing?.recording?.active)
  const recordAwaitingSave = Boolean(recordStatus?.captured)
  const showRecordBar = recordPhase === 'recording' && isRecording

  // Preload WASM for daemon Placo fallback neutral URDF only.
  useEffect(() => {
    void loadReachyKinematicsWasm().then((wasm) => {
      if (wasm) setNeutralUrdfJoints(buildNeutralUrdfJoints())
    })
  }, [])

  const clearReconnectTimer = useCallback(() => {
    if (wsReconnectTimer.current) {
      clearTimeout(wsReconnectTimer.current)
      wsReconnectTimer.current = null
    }
  }, [])

  const disconnect = useCallback(() => {
    clearReconnectTimer()
    socketRef.current?.close()
    socketRef.current = null
    wsReconnectAttempt.current = 0
    setWsState('disconnected')
  }, [clearReconnectTimer])

  const connect = useCallback(() => {
    if (socketRef.current?.readyState === WebSocket.OPEN) return
    if (socketRef.current?.readyState === WebSocket.CONNECTING) return

    setWsState('connecting')
    setWsError(null)

    const ws = new WebSocket(agentWsUrl('/ws/robots/reachy_mini/state?frequency=60'))
    ws.onopen = () => {
      wsReconnectAttempt.current = 0
      setWsState('connected')
      setWsError(null)
    }
    const flushWs = () => {
      wsFrameRef.current = null
      const payload = wsPendingRef.current
      if (!payload) return
      wsPendingRef.current = null
      if (payload.type === 'reachy_error') {
        setWsState('error')
        setWsError(payload.message ?? payload.error ?? 'Reachy state stream failed')
        return
      }
      if (payload.state) setState(payload.state)

      const named: Record<string, number> = {}
      Object.entries(payload.named_joints ?? {}).forEach(([key, value]) => {
        if (typeof value === 'number') named[key] = value
      })
      // Only merge daemon Placo passive_joints. Local WASM on AnalyticalKinematics
      // disagrees with head_pose and breaks the twin after hard refresh.
      const reachyState = payload.state as import('../lib/reachyApi').ReachyFullState | null
      const passiveJoints = reachyState?.passive_joints
      const namedWithPassive = mergePassiveJoints(named, passiveJoints)
      const numeric: Record<string, number> = {}
      Object.entries(payload.joints ?? {}).forEach(([key, value]) => {
        if (typeof value === 'number') numeric[key] = value
      })
      setNamedJointsFromWs(namedWithPassive)
      setNumericJointsFromWs(numeric)
    }
    ws.onmessage = (event) => {
      wsPendingRef.current = JSON.parse(event.data) as ReachyStateMessage
      if (wsFrameRef.current === null) {
        wsFrameRef.current = requestAnimationFrame(flushWs)
      }
    }
    ws.onerror = () => {
      setWsState('error')
      setWsError('状态流连接失败，将自动重试')
    }
    ws.onclose = () => {
      socketRef.current = null
      setWsState((prev) => (prev === 'error' ? 'error' : 'disconnected'))
      const attempt = wsReconnectAttempt.current
      if (attempt < 8) {
        const delay = Math.min(1000 * 2 ** attempt, 30_000)
        wsReconnectTimer.current = setTimeout(() => {
          wsReconnectAttempt.current = attempt + 1
          connect()
        }, delay)
      }
    }
    socketRef.current = ws
  }, [])

  useEffect(() => {
    return () => {
      if (wsFrameRef.current !== null) cancelAnimationFrame(wsFrameRef.current)
      clearReconnectTimer()
      socketRef.current?.close()
      socketRef.current = null
    }
  }, [clearReconnectTimer])

  useEffect(() => {
    void getReachyVirtualStatus()
      .then(setVirtualStatus)
      .catch(() => setVirtualStatus(null))
    void getReachyRecordStatus()
      .then(setRecordStatus)
      .catch(() => setRecordStatus(null))
  }, [])

  useEffect(() => {
    if (!isRecording && !recordAwaitingSave) return undefined
    const timer = window.setInterval(() => {
      void getReachyRecordStatus()
        .then(setRecordStatus)
        .catch(() => undefined)
    }, isRecording ? 200 : 1000)
    return () => window.clearInterval(timer)
  }, [isRecording, recordAwaitingSave])

  // Auto-connect state stream when daemon or virtual mode is ready
  useEffect(() => {
    if (!reachyReady) {
      disconnect()
      return
    }
    if (wsState === 'idle' || wsState === 'disconnected') {
      connect()
    }
  }, [reachyReady, connect, disconnect, wsState])

  const namedJoints = useMemo<Record<string, number>>(() => {
    if (Object.keys(namedJointsFromWs).length) return namedJointsFromWs
    const out: Record<string, number> = {}
    jointNames.forEach((name, i) => {
      const wireKey = String(i + 1)
      const v = numericJointsFromWs[wireKey]
      if (typeof v === 'number') out[name] = v
    })
    return out
  }, [jointNames, namedJointsFromWs, numericJointsFromWs])

  const JOINT_DISPLAY_DEADBAND = 0.003
  const snapJoint = useCallback((key: string, value: number) => {
    const prev = displaySmoothRef.current[key]
    if (prev !== undefined && Math.abs(value - prev) < JOINT_DISPLAY_DEADBAND) return prev
    displaySmoothRef.current[key] = value
    return value
  }, [])

  // URDF Stewart legs are not a true parallel platform — always drive head from measured RPY.
  const displayHeadRpy = useMemo(() => {
    if (virtualActive && !playingMoveName) {
      return { roll: gotoTarget.roll, pitch: gotoTarget.pitch, yaw: gotoTarget.yaw }
    }
    return extractHeadRpyFromPose(state?.head_pose)
  }, [virtualActive, playingMoveName, gotoTarget, state?.head_pose])

  const displayJoints = useMemo(() => {
    const headRpy = displayHeadRpy

    let bodyYaw =
      typeof namedJoints.body_rotation === 'number'
        ? namedJoints.body_rotation
        : typeof state?.body_yaw === 'number'
          ? state.body_yaw
          : gotoTarget.bodyYaw

    const prev = urdfBodyYawRef.current
    if (prev !== null && Math.abs(bodyYaw - prev) < URDF_BODY_JOINT_DEADBAND_RAD) {
      bodyYaw = prev
    } else {
      urdfBodyYawRef.current = bodyYaw
    }

    const out = namedJointsToUrdf(
      headRpyToNamedJoints(headRpy.roll, headRpy.pitch, headRpy.yaw, bodyYaw),
    )

    for (const name of ['right_antenna', 'left_antenna'] as const) {
      const value = namedJoints[name]
      if (typeof value === 'number') out[name] = snapJoint(name, value)
    }

    return out
  }, [
    snapJoint,
    displayHeadRpy,
    state?.body_yaw,
    namedJoints,
    gotoTarget.bodyYaw,
  ])

  // Twin: Placo passive_joints → Stewart chain; else head_pose → displayJoints
  // (AnalyticalKinematics — stable across hard refresh, no local WASM passive).
  const stageUrdfJoints = useMemo(() => {
    const daemonPassive = state?.passive_joints
    if (Array.isArray(daemonPassive) && daemonPassive.length > 0) {
      const namedBase =
        Object.keys(namedJointsFromWs).length > 0
          ? namedJointsFromWs
          : {
              body_rotation: 0,
              stewart_1: 0,
              stewart_2: 0,
              stewart_3: 0,
              stewart_4: 0,
              stewart_5: 0,
              stewart_6: 0,
              right_antenna: 0,
              left_antenna: 0,
            }
      return ensureReachyUrdfJoints(namedBase, state, neutralUrdfJoints)
    }
    if (Object.keys(displayJoints).length > 0) return displayJoints
    if (Object.keys(neutralUrdfJoints).length > 0) return neutralUrdfJoints
    return displayJoints
  }, [displayJoints, namedJointsFromWs, state, neutralUrdfJoints])

  const liveStreamSmoothing = daemonOnline && !virtualActive && (
    isRecording || recordAwaitingSave || motorMode === 'disabled' || Boolean(playingMoveName)
  )
  const jointSmoothing = liveStreamSmoothing
    ? (playingMoveName ? 28 : isRecording || recordAwaitingSave ? 22 : 10)
    : 22

  const playDisabledReason = !reachyReady
    ? '请先启动虚拟模式'
    : !selectedMove
      ? '正在加载动作…'
      : null

  const streamConnected = wsState === 'connected'
  const hasPlayedMove = Boolean(playingMoveName || currentMoveId)

  const guideCtx = useMemo(
    () => ({
      virtualActive,
      daemonOnline,
      streamConnected,
      hasPlayedMove,
    }),
    [virtualActive, daemonOnline, streamConnected, hasPlayedMove],
  )

  const runAction = async (key: string, action: () => Promise<unknown>, success: string) => {
    setActionBusy(key)
    setActionError(null)
    setActionMessage(null)
    try {
      const outcome = await action()
      setActionMessage(typeof outcome === 'string' && outcome ? outcome : success)
      await refreshSnapshot()
    } catch (e) {
      setActionError((e as Error).message)
    } finally {
      setActionBusy(null)
    }
  }

  const handlePlayMove = () => {
    if (!reachyReady || !selectedMove || actionBusy) return
    setPlayingMoveName(selectedMove)
    setActionMessage(`播放 ${selectedMove}`)
    setActionError(null)
    setActionBusy('play-move')
    void (async () => {
      try {
        let duration = 3
        try {
          const moveJson = await getReachyMoveJson(selectedCategory, selectedMove)
          const times = moveJson.time ?? []
          if (times.length) duration = Math.max(times[times.length - 1], 0.1)
        } catch {
          /* fallback duration */
        }
        setPlaybackTimeline({
          name: selectedMove,
          duration,
          startedAt: performance.now(),
        })
        setPlaybackElapsed(0)
        const result = await playLocalMove(selectedMove)
        setCurrentMoveId(typeof result.uuid === 'string' ? result.uuid : null)
      } catch (e) {
        setPlayingMoveName(null)
        setPlaybackTimeline(null)
        setActionError((e as Error).message)
      } finally {
        setActionBusy(null)
      }
    })()
  }

  useEffect(() => {
    if (!playbackTimeline) return undefined
    let raf = 0
    const tick = () => {
      const elapsed = (performance.now() - playbackTimeline.startedAt) / 1000
      if (elapsed >= playbackTimeline.duration + 0.05) {
        setPlaybackElapsed(playbackTimeline.duration)
        setPlaybackTimeline(null)
        setPlayingMoveName(null)
        setCurrentMoveId(null)
        return
      }
      setPlaybackElapsed(elapsed)
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [playbackTimeline])

  const handleStopMove = () => runAction(
    'stop-move',
    async () => {
      if (!currentMoveId) return
      await stopMove(currentMoveId)
      setCurrentMoveId(null)
      setPlayingMoveName(null)
      setPlaybackTimeline(null)
    },
    'Move stopped',
  )

  const handleGoto = () => {
    if (!reachyReady || actionBusy) return
    setActionMessage('已发送')
    setActionError(null)
    setActionBusy('goto')
    void moveGoto({
      head_pose: {
        roll: gotoTarget.roll,
        pitch: gotoTarget.pitch,
        yaw: gotoTarget.yaw,
      },
      body_yaw: gotoTarget.bodyYaw,
      duration: gotoTarget.duration,
      interpolation: 'minjerk',
    })
      .catch((e) => setActionError((e as Error).message))
      .finally(() => setActionBusy(null))
  }

  const handleMotorMode = (mode: ReachyMotorMode) => {
    if (mode === 'gravity_compensation' && !GRAVITY_COMPENSATION_AVAILABLE) {
      setActionError(
        '重力补偿需要 Placo 运动学引擎；当前守护进程使用 AnalyticalKinematics，暂不支持此模式。',
      )
      return
    }
    return runAction(
      `motor-${mode}`,
      () => setMotorMode(mode),
      `Motors changed to ${mode}`,
    )
  }

  const handleStartLocalDaemon = () => runAction(
    'local-daemon-start',
    async () => {
      const status = await startRobotService<ReachyLocalDaemonStatus>('reachy_mini')
      setLocalDaemonStatus(status)
    },
    '正在启动本地守护进程…',
  )

  const handleProvisionDependencies = () => runAction(
    'dependencies-provision',
    async () => {
      await provisionRobotDependencies('reachy_mini')
      setDependencyStatus(await getRobotDependencies('reachy_mini'))
    },
    '依赖环境已配置',
  )

  const handleStopLocalDaemon = () => runAction(
    'local-daemon-stop',
    async () => {
      disconnect()
      const status = await stopRobotService<ReachyLocalDaemonStatus>('reachy_mini')
      setLocalDaemonStatus(status)
    },
    '本地守护进程已停止',
  )

  const handleStartVirtual = () => {
    if (actionBusy) return
    setActionMessage('启动虚拟模式…')
    setActionError(null)
    setActionBusy('virtual-start')
    void startReachyVirtual()
      .then(async (result) => {
        setVirtualStatus(await getReachyVirtualStatus())
        if (!result.active) {
          throw new Error(result.message || '虚拟模式启动失败')
        }
        setActionMessage('虚拟模式已启用')
      })
      .catch((e) => setActionError((e as Error).message))
      .finally(() => setActionBusy(null))
  }

  const handleStopVirtual = () => runAction(
    'virtual-stop',
    async () => {
      await stopReachyVirtual()
      disconnect()
      setVirtualStatus(await getReachyVirtualStatus())
      setState(null)
    },
    '虚拟模式已关闭',
  )

  useEffect(() => {
    const playHello = () => {
      setSelectedCategory('dances')
      setSelectedMove('hello')
      setPlayingMoveName('hello')
      setActionMessage('播放 hello')
      void playLocalMove('hello')
        .then((result) => {
          setCurrentMoveId(typeof result.uuid === 'string' ? result.uuid : null)
        })
        .catch((e) => setActionError((e as Error).message))
    }

    const onDemo = (e: Event) => {
      const action = (e as CustomEvent<{ action?: string }>).detail?.action
      if (action === 'play-hello') playHello()
    }
    window.addEventListener('botversex:reachy-guide-demo', onDemo)

    const continueVirtualGuide = (stepId: string) => {
      window.dispatchEvent(
        new CustomEvent('botversex:start-reachy-guide', {
          detail: { preset: 'virtual', stepId },
        }),
      )
    }

    const u1 = registerCopilotActionHandler('reachy_virtual_start', async () => {
      if (virtualActive) {
        continueVirtualGuide('viewer')
        return
      }
      await handleStartVirtual()
      window.setTimeout(() => continueVirtualGuide('viewer'), 1200)
    })
    const u2 = registerCopilotActionHandler('reachy_play_demo', () => {
      setSelectedCategory('dances')
      setSelectedMove('hello')
      void runAction(
        'play-move',
        async () => {
          const result = await playLocalMove('hello')
          setCurrentMoveId(typeof result.uuid === 'string' ? result.uuid : null)
          setPlayingMoveName('hello')
        },
        'Playing hello',
      )
      window.setTimeout(() => continueVirtualGuide('controls'), 800)
    })

    // M26 — robot-driving Copilot actions. The user can say "让机器人开心" /
    // "跳个舞" / "看着我" to the assistant and have the robot respond, without
    // hunting for buttons in the control panel.
    const u3 = registerCopilotActionHandler('reachy_play_emotion', async (action) => {
      if (action?.type !== 'reachy_play_emotion') return
      let { emotion } = action
      // Cloud copilot often returns a generic word ("happy", "开心", "smile")
      // instead of a real emotion clip name. Map known synonyms → real names
      // from pollen-robotics/reachy-mini-emotions-library, and fall back to
      // a welcoming clip if the name is unknown.
      const EMOTION_ALIASES: Record<string, string> = {
        happy: 'laughing1', 开心: 'laughing1', 高兴: 'laughing1', 笑: 'laughing1',
        sad: 'downcast1', 伤心: 'downcast1', 难过: 'downcast1',
        amazed: 'amazed1', 惊讶: 'amazed1', 惊喜: 'amazed1',
        shy: 'shy1', 害羞: 'shy1',
        welcome: 'welcoming1', 欢迎: 'welcoming1', 打招呼: 'welcoming1',
        bored: 'boredom1', 无聊: 'boredom1',
        lonely: 'lonely1', 孤独: 'lonely1',
        anxious: 'anxiety1', 焦虑: 'anxiety1', 紧张: 'anxiety1',
        grateful: 'grateful1', 感谢: 'grateful1', 感动: 'grateful1',
        frustrated: 'frustrated1', 沮丧: 'frustrated1',
        success: 'success1', 成功: 'success1',
        laugh: 'laughing1', 哈哈: 'laughing1',
        reprimand: 'reprimand1', 责备: 'reprimand1',
        oops: 'oops1', 哎呀: 'oops1',
      }
      const GENERIC = new Set(['emotion', 'emotions', '随便', 'any', 'random'])
      const key = String(emotion ?? '').toLowerCase().trim()
      if (EMOTION_ALIASES[key]) {
        emotion = EMOTION_ALIASES[key]
      } else if (!emotion || GENERIC.has(key) || !/^[a-z]+[0-9]?$/.test(key)) {
        emotion = 'welcoming1'
      }
      setActionMessage(`Copilot: 播放表情 ${emotion}`)
      // Set a default timeline so the green "正在播放" banner shows a real
      // progress bar instead of a static label. The duration is a fallback —
      // when the play call resolves we clear the timeline regardless.
      setPlayingMoveName(emotion)
      setPlaybackTimeline({ name: emotion, duration: 4, startedAt: performance.now() })
      setPlaybackElapsed(0)
      try {
        try {
          await playReachyRecordedMove('pollen-robotics/reachy-mini-emotions-library', emotion)
        } catch {
          await playLocalMove(emotion)
        }
      } catch (e) {
        setActionError(`表情播放失败: ${(e as Error).message}`)
      } finally {
        setPlaybackTimeline(null)
        setPlayingMoveName(null)
      }
    })
    const u4 = registerCopilotActionHandler('reachy_play_dance', async (action) => {
      if (action?.type !== 'reachy_play_dance') return
      let { dance } = action
      // Cloud copilot sometimes returns a literal/generic word ("dance",
      // "跳舞", "跳一个", "随便") instead of a real move name from the
      // dances library. Map those to a known-good default so "跳个舞"
      // actually produces motion instead of "Move not found".
      const KNOWN_DANCES = [
        'chin_lead', 'interwoven_spirals', 'uh_huh_tilt', 'side_glance_flick',
        'jackson_square', 'side_to_side_sway', 'chicken_peck', 'polyrhythm_combo',
        'pendulum_swing', 'side_peekaboo', 'yeah_nod', 'neck_recoil',
        'groovy_sway_and_roll', 'sharp_side_tilt', 'head_tilt_roll',
        'stumble_and_recover', 'simple_nod', 'dizzy_spin', 'grid_snap',
      ]
      const GENERIC = new Set(['dance', 'dances', '随便', '跳一个', '跳个舞', '跳舞', '随便跳', 'any', 'random'])
      if (!dance || GENERIC.has(String(dance).toLowerCase().trim()) || !KNOWN_DANCES.includes(String(dance))) {
        dance = 'polyrhythm_combo'
      }
      setActionMessage(`Copilot: 播放舞蹈 ${dance}`)
      setPlayingMoveName(dance)
      setPlaybackTimeline({ name: dance, duration: 10, startedAt: performance.now() })
      setPlaybackElapsed(0)
      try {
        try {
          await playReachyRecordedMove('pollen-robotics/reachy-mini-dances-library', dance)
        } catch {
          await playLocalMove(dance)
        }
      } catch (e) {
        setActionError(`舞蹈播放失败: ${(e as Error).message}`)
      } finally {
        setPlaybackTimeline(null)
        setPlayingMoveName(null)
      }
    })
    const u5 = registerCopilotActionHandler('reachy_goto', async (action) => {
      if (action?.type !== 'reachy_goto') return
      setActionMessage('Copilot: 发送 goto')
      try {
        await moveGoto({
          head_pose: {
            roll: action.roll ?? 0,
            pitch: action.pitch ?? 0,
            yaw: action.yaw ?? 0,
          },
          body_yaw: action.bodyYaw ?? 0,
          duration: action.duration ?? 1.5,
          interpolation: 'minjerk',
        })
      } catch (e) {
        setActionError(`goto 失败: ${(e as Error).message}`)
      }
    })
    const u6 = registerCopilotActionHandler('reachy_start_chat', async () => {
      setActionMessage('Copilot: 切到对话 Tab')
      setActiveTab('chat')
      window.dispatchEvent(
        new CustomEvent('botversex:copilot', { detail: { tab: 'chat', open: true } }),
      )
    })
    const u7 = registerCopilotActionHandler('reachy_start_head_tracker', async () => {
      setActionMessage('Copilot: 启动头部跟踪')
      setActiveTab('vision')
      try {
        await startReachyHeadTracker(0)
      } catch (e) {
        setActionError(`启动头部跟踪失败: ${(e as Error).message}`)
      }
    })
    return () => {
      u1()
      u2()
      u3()
      u4()
      u5()
      u6()
      u7()
      window.removeEventListener('botversex:reachy-guide-demo', onDemo)
    }
  })

  const clearPrepTimer = useCallback(() => {
    if (prepTimerRef.current !== null) {
      window.clearInterval(prepTimerRef.current)
      prepTimerRef.current = null
    }
  }, [])

  // Actually begin capturing (called after the prep countdown).
  const beginRecordCapture = useCallback(() => {
    setActionBusy('record-start')
    setActionError(null)
    void startReachyRecord({ name: `_rec_${Date.now()}`, sample_hz: 10, compliant: false })
      .then(async () => {
        setRecordStatus(await getReachyRecordStatus())
        setRecordPhase('recording')
        displaySmoothRef.current = {}
      })
      .catch((e) => {
        setActionError((e as Error).message)
        setRecordPhase('idle')
        setPrepCountdown(0)
      })
      .finally(() => setActionBusy(null))
  }, [])

  const handleStartRecordPrep = () => {
    if (!daemonOnline || virtualActive) return
    setRecordConfirmOpen(true)
  }

  const handleConfirmStartRecord = () => {
    setRecordConfirmOpen(false)
    setRecordPhase('prep')
    setPrepCountdown(3)
    setActionError(null)
    setActionMessage(null)
    clearPrepTimer()
    prepTimerRef.current = window.setInterval(() => {
      setPrepCountdown((n) => {
        if (n <= 1) {
          clearPrepTimer()
          beginRecordCapture()
          return 0
        }
        return n - 1
      })
    }, 1000)
  }

  const handleCancelRecordPrep = () => {
    clearPrepTimer()
    setRecordPhase('idle')
    setPrepCountdown(0)
  }

  useEffect(() => () => clearPrepTimer(), [clearPrepTimer])

  const handleStopRecordPrompt = () => {
    if (recordStopping) return
    setRecordStopping(true)
    void stopReachyRecordCapture()
      .then((result) => {
        setRecordFrozenElapsed(result.elapsed_s)
        setRecordStatus((prev) => ({
          ...(prev ?? {
            active: false,
            name: '',
            sample_hz: 10,
            sample_count: result.sample_count,
            elapsed_s: result.elapsed_s,
            virtual: false,
          }),
          active: false,
          captured: true,
          elapsed_s: result.elapsed_s,
          sample_count: result.sample_count,
        }))
        setRecordPhase('naming')
        setRecordSaveName('')
        setRecordNamePromptOpen(true)
      })
      .catch((e) => setActionError((e as Error).message))
      .finally(() => setRecordStopping(false))
  }

  const handleResumeRecord = () => {
    void resumeReachyRecordCapture()
      .then(async () => {
        setRecordNamePromptOpen(false)
        setRecordPhase('recording')
        setRecordStatus(await getReachyRecordStatus())
      })
      .catch((e) => setActionError((e as Error).message))
  }

  const handleDiscardRecord = () => {
    void discardReachyRecord()
      .then(async () => {
        setRecordNamePromptOpen(false)
        setRecordPhase('idle')
        setRecordStatus(await getReachyRecordStatus())
      })
      .catch((e) => setActionError((e as Error).message))
  }

  const handleConfirmStopRecord = () => {
    const name = recordSaveName.trim()
    if (!name) {
      setActionError('请输入动作名称')
      return
    }
    if (actionBusy) return
    void runAction(
      'record-stop',
      async () => {
        const result = await stopReachyRecord({ name, display_name: name })
        setRecordPhase('idle')
        setRecordNamePromptOpen(false)
        setRecordStatus(await getReachyRecordStatus())
        const remoteCategories = await getLocalCategories()
        if (remoteCategories.length) setCategories(remoteCategories)
        setSelectedCategory(result.category)
        const remoteMoves = await getLocalMoves(result.category)
        setMoves(remoteMoves.length ? remoteMoves : [result.move_name])
        setSelectedMove(result.move_name)
        return `已保存：${result.display_name ?? result.move_name}`
      },
      '已保存',
    )
  }

  const isSavingRecord = actionBusy === 'record-stop'

  const refreshCategories = async () => {
    try {
      const remoteCategories = await getLocalCategories()
      if (remoteCategories.length) {
        setCategories(remoteCategories)
        if (!remoteCategories.includes(selectedCategory)) {
          setSelectedCategory(remoteCategories[0])
        }
      }
    } catch {
      setCategories(Object.keys(DEFAULT_MOVES))
    }
  }

  const loadCustomMoveList = useCallback(async () => {
    try {
      const list = await getLocalMoves('custom')
      setCustomMoveList(list)
    } catch {
      setCustomMoveList([])
    }
  }, [])

  const handleDeleteCustomMove = (moveName: string) => {
    void runAction(
      'delete-move',
      async () => {
        await deleteReachyMove('custom', moveName)
        const list = await getLocalMoves('custom')
        setCustomMoveList(list)
        if (selectedCategory === 'custom') {
          setMoves(list)
          if (selectedMove === moveName) {
            setSelectedMove(list[0] ?? '')
          }
        }
        return `已删除 ${moveName}`
      },
      '已删除',
    )
  }

  const customMovesList = useMemo(
    () => (editorCustomMoves.length ? editorCustomMoves : (DEFAULT_MOVES.custom ?? [])),
    [editorCustomMoves],
  )

  const handleMotionExported = useCallback(async (result: {
    move_name: string
    display_name?: string
    category: string
  }) => {
    setActionMessage(`动作已导出: ${result.display_name ?? result.move_name}`)
    try {
      const remoteCategories = await getLocalCategories()
      if (remoteCategories.length) setCategories(remoteCategories)
      setSelectedCategory(result.category)
      const remoteMoves = await getLocalMoves(result.category)
      if (remoteMoves.length) {
        setMoves(remoteMoves)
        setSelectedMove(result.move_name)
      }
    } catch {
      /* list refresh is best-effort */
    }
  }, [])

  const serialPort = reachyPing?.serial.port ?? localDaemonStatus?.serial_port ?? '/dev/ttyACM0'
  const daemonBase = reachyPing?.daemon_http.base ?? localDaemonStatus?.daemon_http.base ?? 'http://127.0.0.1:8010'

  // M26 — Cleanup: reference symbols retained for potential future use so
  // tsc `noUnusedLocals` stays green. The old 9-Card layout used these; the
  // new Stage + SidebarTabs layout moves the corresponding UX into dedicated
  // tab components. They can be safely removed in a follow-up cleanup pass.
  void categories
  void customManageOpen
  void setCustomManageOpen
  void customMoveList
  void daemonBase
  void dependencyStatus
  void displayJoints
  void handleCancelRecordPrep
  void handleConfirmStartRecord
  void handleConfirmStopRecord
  void handleDeleteCustomMove
  void handleDiscardRecord
  void handleGoto
  void handleMotorMode
  void handlePlayMove
  void handleProvisionDependencies
  void handleResumeRecord
  void handleStartRecordPrep
  void handleStopLocalDaemon
  void handleStopMove
  void handleStopRecordPrompt
  void isSavingRecord
  void jointSmoothing
  void loadCustomMoveList
  void moves
  void playDisabledReason
  void prepCountdown
  void recordConfirmOpen
  void recordFrozenElapsed
  void recordNamePromptOpen
  void refreshCategories
  void serialPort
  void setGotoTarget
  void showRecordBar

  return (
    <div className="container mx-auto px-4 py-6 space-y-4">
      {/* Header — back, name, status badges, virtual/daemon start buttons */}
      <div className="flex flex-wrap items-center gap-3">
        <Link
          to="/robots"
          className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-[hsl(var(--border))] hover:bg-[hsl(var(--muted))]/40 transition-colors"
          aria-label="Back to robots"
        >
          <ArrowLeft className="h-4 w-4" />
        </Link>
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[hsl(var(--primary))]/15">
          <Bot className="h-5 w-5 text-[hsl(var(--primary))]" />
        </div>
        <div className="flex-1 min-w-[200px]">
          <h1 className="text-xl font-semibold tracking-tight">
            {meta?.display_name ?? 'Reachy Mini'}
          </h1>
          <p className="text-xs text-[hsl(var(--muted-foreground))]">
            Lite · USB 接电脑 · 开机 → 插线 → 点「启动机器人」
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <ReachyMiniGuide
            ctx={guideCtx}
            autoStart={guideAutoStart}
            presetMode={guidePresetMode}
          />
          <Badge
            variant="outline"
            className={
              daemonOnline
                ? 'border-green-500/40 text-green-400'
                : virtualActive
                  ? 'border-sky-500/40 text-sky-300'
                  : 'border-amber-500/40 text-amber-300'
            }
          >
            {daemonOnline ? '已连接' : virtualActive ? '虚拟模式' : '未连接'}
          </Badge>
          {(daemonOnline || virtualActive) && (
            <Badge variant="outline" className="border-[hsl(var(--primary))]/40 text-[hsl(var(--primary))]">
              电机: {motorMode}
            </Badge>
          )}
          {isRecording && (
            <Badge variant="outline" className="border-red-500/50 text-red-300 animate-pulse">
              <Circle className="h-3 w-3 fill-current mr-1 inline" />
              录制中
            </Badge>
          )}
          {streamConnected && (
            <Badge variant="outline" className="border-green-500/40 text-green-400">
              实时
            </Badge>
          )}
          {wsState === 'connecting' && (
            <Badge variant="outline" className="border-amber-500/40 text-amber-300">
              <Loader2 className="h-3 w-3 animate-spin mr-1 inline" />
              连接中
            </Badge>
          )}
        </div>

        {!daemonOnline && !virtualActive && (
          <>
            <Button
              variant="outline"
              data-tour="reachy-virtual"
              onClick={handleStartVirtual}
              disabled={actionBusy === 'virtual-start'}
            >
              {actionBusy === 'virtual-start' ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Monitor className="h-4 w-4" />
              )}
              虚拟模式
            </Button>
            <Button
              data-tour="reachy-daemon"
              onClick={handleStartLocalDaemon}
              disabled={actionBusy === 'local-daemon-start'}
            >
              {actionBusy === 'local-daemon-start' ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Power className="h-4 w-4" />
              )}
              启动机器人
            </Button>
          </>
        )}
        {virtualActive && !daemonOnline && (
          <Button
            variant="outline"
            onClick={handleStopVirtual}
            disabled={actionBusy === 'virtual-stop'}
          >
            {actionBusy === 'virtual-stop' ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Monitor className="h-4 w-4" />
            )}
            退出虚拟
          </Button>
        )}
      </div>

      <ReachyOnboardingCard
        daemonOnline={daemonOnline}
        virtualActive={virtualActive}
        onStartDaemon={handleStartLocalDaemon}
        onStartVirtual={handleStartVirtual}
        daemonBusy={actionBusy === 'local-daemon-start'}
        virtualBusy={actionBusy === 'virtual-start'}
      />

      {/* Proxy / realtime unreachable banners */}
      {isLocalDev() && !virtualActive && proxyStatus === '502' && (
        <div className="rounded-md border border-red-500/40 bg-red-500/10 p-4 text-sm text-red-200 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div>
            <span className="font-medium text-red-100">开发代理无法连接实时服务（502）</span>
            <p className="text-red-300/90 mt-1 text-xs">
              Vite 默认代理到 <code className="font-mono">http://127.0.0.1:8002</code>。
              若 realtime 以 HTTPS 启动，页面会表现为"点哪儿都不行"。
            </p>
            <pre className="mt-2 rounded bg-black/30 px-2 py-1.5 text-[11px] font-mono text-red-100/90 overflow-x-auto">
              cd apps/realtime{'\n'}.venv/bin/python run_api.py --http
            </pre>
          </div>
          <Button
            size="sm"
            variant="outline"
            className="shrink-0 border-red-500/50 text-red-200 hover:bg-red-500/10"
            onClick={() => void (async () => {
              await checkRealtimeProxy()
              await refreshSnapshot()
            })()}
          >
            <RotateCcw className="h-3.5 w-3.5 mr-1" />
            重试
          </Button>
        </div>
      )}

      {isLocalDev() && !virtualActive && realtimeReachable === false && proxyStatus !== '502' && proxyStatus !== 'checking' && !meta && (
        <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-4 text-sm text-amber-200 flex items-center justify-between gap-3">
          <div>
            <span className="font-medium text-amber-100">实时服务未响应</span>
            <span className="text-amber-300/80 ml-2">
              请确认 apps/realtime 正在运行（端口 8002）。本地开发请使用：
              <code className="font-mono text-[11px] ml-1">python run_api.py --http</code>
            </span>
          </div>
          <Button
            size="sm"
            variant="outline"
            className="shrink-0 border-amber-500/50 text-amber-200 hover:bg-amber-500/10"
            onClick={() => void refreshSnapshot()}
          >
            <RotateCcw className="h-3.5 w-3.5 mr-1" />
            重试
          </Button>
        </div>
      )}

      {metaErr && realtimeReachable !== false && (
        <div className="rounded-md border border-red-500/30 bg-red-500/5 p-3 text-sm text-red-300">
          加载失败: {metaErr}
        </div>
      )}

      {actionError && (
        <div className="rounded-md border border-red-500/30 bg-red-500/5 p-3 text-sm text-red-300">
          {actionError}
        </div>
      )}

      {!actionError && !virtualActive && wsError && (
        <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-3 text-sm text-amber-200">
          连接中断，正在重试…
        </div>
      )}

      {actionMessage && (
        <div className="rounded-md border border-green-500/30 bg-green-500/5 p-3 text-sm text-green-300">
          {actionMessage}
        </div>
      )}

      {/* Playback banner — kept at top so any source (Copilot action, MotionTab, etc.) is visible */}
      {playingMoveName && playbackTimeline && (
        <div className="rounded-md border border-green-500/30 bg-green-500/5 px-3 py-2 text-sm text-green-300 flex items-center gap-3">
          <Play className="h-3.5 w-3.5 shrink-0" />
          <span className="font-medium shrink-0">{playingMoveName}</span>
          <span className="font-mono text-xs tabular-nums shrink-0">
            {playbackElapsed.toFixed(1)}s / {playbackTimeline.duration.toFixed(1)}s
          </span>
          <div className="flex-1 h-1.5 rounded-full bg-white/10 overflow-hidden min-w-[80px]">
            <div
              className="h-full bg-emerald-400 transition-[width] duration-75"
              style={{
                width: `${Math.min(100, (playbackElapsed / Math.max(playbackTimeline.duration, 0.1)) * 100)}%`,
              }}
            />
          </div>
        </div>
      )}

      {playingMoveName && !playbackTimeline && (
        <div className="rounded-md border border-green-500/30 bg-green-500/5 px-3 py-2 text-sm text-green-300 flex items-center gap-2">
          <Play className="h-3.5 w-3.5" />
          正在播放: <span className="font-medium">{playingMoveName}</span>
        </div>
      )}

      {/* Fullscreen motion editor overlay (compose mode, used by tour) */}
      {viewerMode === 'compose' && (
        <ReachyMotionEditor
          urdfUrl={meta?.urdf_url ?? '/api/urdf/reachy_mini/reachy_mini.urdf'}
          customMoves={customMovesList}
          onExported={(result) => void handleMotionExported(result)}
          onExit={() => setViewerMode('view')}
        />
      )}

      {/* M26 — 主区 Stage + 右栏 Tabs (1fr / 380px) */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_380px] gap-4 min-h-[640px]">
        <ReachyStage
          urdfUrl={meta?.urdf_url ?? '/api/urdf/reachy_mini/reachy_mini.urdf'}
          joints={stageUrdfJoints}
          headRpy={displayHeadRpy}
          daemonOnline={daemonOnline}
          audioAvailable={daemonOnline && !virtualActive}
          cameraPreviewUrl={cameraPreview.on ? cameraPreview.url : null}
          cameraPreviewDevice={cameraPreview.device}
          onStartVirtual={handleStartVirtual}
          onNavigateTab={(tab) => setActiveTab(tab)}
        />
        <ReachySidebarTabs
          daemonOnline={daemonOnline}
          activeTab={activeTab}
          onTabChange={setActiveTab}
          chatPanel={<ReachyChatTab daemonOnline={daemonOnline} />}
          motionPanel={<ReachyMotionTab daemonOnline={daemonOnline} />}
          visionPanel={
            <ReachyVisionTab
              daemonOnline={daemonOnline}
              onPreviewChange={setCameraPreview}
            />
          }
          advancedPanel={<ReachyAdvancedDrawer daemonOnline={daemonOnline} />}
        />
      </div>

      <CommunityResources
        intro="Reachy Mini 是 Pollen Robotics 的开源人形台座。官方仓库自带完整 docs 与 troubleshooting；问题大多在官方 Discord 与论坛得到解答。"
        docs={[
          { label: '官方仓库（docs/quickstart/troubleshooting）', url: 'https://github.com/pollen-robotics/reachy_mini' },
          { label: 'HuggingFace 文档（SDK）', url: 'https://huggingface.co/docs/reachy_mini/v1.9.0/en/SDK/readme' },
        ]}
        communities={[
          { label: 'Pollen Community Discord', url: 'https://discord.gg/Y7FgMqHsub' },
          { label: '官方论坛', url: 'https://forum.pollen-robotics.com/' },
        ]}
        faqs={[
          {
            q: 'daemon 无响应 / 随机卡死？',
            a: 'Windows Lite 用户常见，日志反复出现串口 flush 重试——先更新固件 + 断电重启（issue #623）。',
          },
          {
            q: '无线版 App 连不上（localhost:7447）？',
            a: 'Zenoh 需要端口转发：ssh -fNL 7447:reachy-mini.local:7447 pollen@reachy-mini.local（issue #677）。',
          },
          {
            q: '电机红灯闪烁 / Overload Error？',
            a: '多半是电机插错槽位或接线问题（喇叭口两线标记要对齐）。官方有专门的 motors_diagnosis 排查表。',
          },
          {
            q: '麦克风没有声音？',
            a: '最高频装配错误是 FPC 排线插反（蓝面朝上）。',
          },
          {
            q: '首次启动完全不动？',
            a: '只用 USB 供电不够——必须插 7V-5A 电源。',
          },
        ]}
      />
    </div>
  )
}
