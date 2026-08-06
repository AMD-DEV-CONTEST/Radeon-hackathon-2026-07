/**
 * M27 — B601-RS runtime page (/robots/b601_rs)
 *
 * 默认新手上手；工作台与新手上手平级。
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ArrowLeft, Bot, Loader2, Square } from 'lucide-react'
import { registerCopilotActionHandler } from '../lib/copilotAgent'
import { useB601LiveJoints } from '../hooks/useB601LiveJoints'
import { useB601GravityCompLiveJoints } from '../hooks/useB601GravityCompLiveJoints'
import { SetupProvider, useSetup } from '../components/setup/SetupProvider'
import { SetupSidebar } from '../components/setup/SetupSidebar'
import { SetupStepCard } from '../components/setup/SetupStepCard'
import { Button } from '../components/ui/button'
import { Badge } from '../components/ui/badge'
import { B601Stage, type B601StageFocus } from '../components/b601/B601Stage'
import { B601SidebarTabs, type B601Tab } from '../components/b601/B601SidebarTabs'
import { B601TeleopTab } from '../components/b601/B601TeleopTab'
import { B601RecordTab } from '../components/b601/B601RecordTab'
import { B601MotionTab } from '../components/b601/B601MotionTab'
import { B601VisionTab } from '../components/b601/B601VisionTab'
import { B601AdvancedDrawer } from '../components/b601/B601AdvancedDrawer'
import { B601ConnectPanel } from '../components/b601/B601ConnectPanel'
import { CommunityResources } from '../components/features/CommunityResources'
import { B601CalibrationPanel } from '../components/b601/B601CalibrationPanel'
import { B601JointPlayPanel } from '../components/b601/B601JointPlayPanel'
import { B601ActivityPanel } from '../components/b601/B601ActivityPanel'
import { B601AlignmentPanel } from '../components/b601/B601AlignmentPanel'
import { B601KinematicsTab } from '../components/b601/B601KinematicsTab'
import { B601GravityCompPanel } from '../components/b601/B601GravityCompPanel'
import { B601Ros2Panel } from '../components/b601/B601Ros2Panel'
import { b601DefaultJointPose, b601JointsToUrdf, b601MotorJointsForViewer, b601MotorRadToUrdf } from '../lib/b601Joints'
import {
  b601CalibrateContinue,
  b601CalibrateStart,
  b601CalibrateStatus,
  b601CalibrateStop,
  b601Disable,
  b601InferenceStart,
  b601InferenceStatus,
  b601InferenceStopSafe,
  b601RecordStatus,
  b601Recover,
  b601OneClickTeleopStart,
  b601TeleopStartWithConfirm,
  b601TeleopStatus,
  b601TeleopStopSafe,
  b601TeleopAlignment,
  waitForB601TeleopReady,
  B601ArmsNotAlignedError,
  getB601Config,
  type B601Alignment,
  refreshB601Health,
  b601Snapshot,
  isB601HardwareReady,
  isB601BrowseOnly,
  isB601ReadyForTeleop,
  loadB601CameraPrefs,
  setB601Config,
  type B601CameraPrefs,
  type B601Health,
} from '../lib/b601Api'
import { b601GravityCompStatus } from '../lib/b601Ros2Api'
import { authJson } from '../lib/auth'
import { useAuth } from '../lib/authContext'
import type { TrainingJobDTO } from '../types/training'
import { useB601Activity } from '../lib/useB601Activity'

function B601EmergencyBar({
  running,
  stopping,
  onStop,
  mode = 'teleop',
}: {
  running: boolean
  stopping?: boolean
  onStop: () => void
  /** teleop | inference — copy + button label */
  mode?: 'teleop' | 'inference'
}) {
  if (!running && !stopping) return null
  const idleLabel =
    mode === 'inference'
      ? '推理运行中 — 策略在驱动从臂，异常立刻急停'
      : '遥操运行中 — 从臂跟主臂动，周围留空，用完请停止'
  const busyLabel = mode === 'inference' ? '正在停止推理并卸力…' : '正在卸力并停止遥操…'
  const btnIdle = mode === 'inference' ? '急停（停推理+卸力）' : '停止遥操'
  return (
    <div className="fixed bottom-20 inset-x-0 z-[60] flex justify-center px-4 pointer-events-none">
      <div className="pointer-events-auto flex flex-wrap items-center justify-center gap-3 rounded-2xl border-2 border-red-500 bg-red-950/95 px-5 py-3.5 shadow-2xl">
        <span className="text-sm font-semibold text-red-50">
          {stopping ? busyLabel : idleLabel}
        </span>
        <Button
          variant="destructive"
          size="lg"
          className="h-11 min-w-[10rem] text-base font-bold"
          disabled={stopping}
          onClick={onStop}
        >
          {stopping ? (
            <Loader2 className="mr-1.5 h-5 w-5 animate-spin" />
          ) : (
            <Square className="mr-1.5 h-5 w-5 fill-current" />
          )}
          {stopping ? '卸力中…' : btnIdle}
        </Button>
      </div>
    </div>
  )
}

function B601WizardBody({ onBackToWorkspace }: { onBackToWorkspace: () => void }) {
  const { state, markComplete, goNext, steps, setLastDataset } = useSetup()
  const [health, setHealth] = useState<B601Health | null>(null)
  const [busy, setBusy] = useState(false)
  const [teleopPhase, setTeleopPhase] = useState<string | null>(null)
  const [teleopRunning, setTeleopRunning] = useState(false)
  const [teleopStarting, setTeleopStarting] = useState(false)
  const [stopping, setStopping] = useState(false)
  const [teleopTested, setTeleopTested] = useState(false)
  const [recovering, setRecovering] = useState(false)
  const [calibrateRunning, setCalibrateRunning] = useState(false)
  const [calibrateTarget, setCalibrateTarget] = useState<string | null>(null)
  const [calibrateLog, setCalibrateLog] = useState<string[]>([])
  const [connecting, setConnecting] = useState(true)
  const [playPose, setPlayPose] = useState(b601DefaultJointPose)
  const [motorZeroBaseline, setMotorZeroBaseline] = useState<Record<string, number> | null>(null)
  const playUrdfJoints = useMemo(() => b601JointsToUrdf(playPose), [playPose])
  const [recordRunning, setRecordRunning] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [alignment, setAlignment] = useState<B601Alignment | null>(null)
  const [checkingAlignment, setCheckingAlignment] = useState(false)
  const [alignmentHint, setAlignmentHint] = useState<string | null>(null)
  const { entries: activity, log: logActivity } = useB601Activity()
  const repoPrefix = health?.arm_variant === 'dm' ? 'b601-dm' : 'b601-rs'

  const pollHealth = useCallback(async () => {
    try {
      const h = await refreshB601Health({
        skipAutoProbe: busy || checkingAlignment || teleopRunning || stopping,
      })
      setHealth(h)
      if (h.ok) markComplete('connect', true)
      try {
        const cs = await b601CalibrateStatus()
        setCalibrateRunning(cs.running)
        setCalibrateTarget(cs.calibrate_target ?? null)
        setCalibrateLog(cs.log_tail ?? [])
      } catch {
        /* optional */
      }
      return h
    } catch (e) {
      if (!busy && !checkingAlignment && !teleopRunning) {
        setMsg(e instanceof Error ? e.message : '无法连接 Local Agent')
      }
      return null
    } finally {
      setConnecting(false)
    }
  }, [markComplete, busy, checkingAlignment, teleopRunning, stopping])

  const pollTeleop = useCallback(async () => {
    try {
      const s = await b601TeleopStatus()
      setTeleopRunning(Boolean(s.running && s.healthy !== false))
      setTeleopStarting(Boolean(s.starting && !s.running))
      if (s.starting && !teleopPhase) {
        setTeleopPhase('正在启动官方遥操…')
      }
      if (!s.starting && !s.running && teleopPhase?.includes('启动')) {
        setTeleopPhase(null)
      }
    } catch {
      setTeleopRunning(false)
      setTeleopStarting(false)
    }
  }, [teleopPhase])

  const stopTeleop = useCallback(async () => {
    if (stopping) return
    setStopping(true)
    setTeleopRunning(false)
    setTeleopPhase('卸力中…')
    logActivity('teleop_stop')
    try {
      await b601TeleopStopSafe()
      setTeleopTested(true)
      markComplete('teleop', true)
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '停止遥操失败')
    } finally {
      setStopping(false)
      setTeleopPhase(null)
      try {
        const s = await b601TeleopStatus()
        setTeleopRunning(Boolean(s.running && s.healthy !== false))
      } catch {
        setTeleopRunning(false)
      }
    }
  }, [markComplete, logActivity, stopping])

  useEffect(() => {
    setConnecting(true)
    void pollHealth()
    const t = setInterval(() => void pollHealth(), teleopRunning ? 15000 : 8000)
    return () => clearInterval(t)
  }, [pollHealth, teleopRunning])

  useEffect(() => {
    void pollTeleop()
    const t = setInterval(() => void pollTeleop(), 2000)
    return () => clearInterval(t)
  }, [pollTeleop])

  const { joints: liveJoints } = useB601LiveJoints(teleopRunning)
  const liveUrdfJoints = useMemo(() => b601JointsToUrdf(liveJoints), [liveJoints])
  const stagePlayJoints = teleopRunning ? liveUrdfJoints : playUrdfJoints

  useEffect(() => {
    const u1 = registerCopilotActionHandler('b601_run_health_check', async () => { await pollHealth() })
    const u2 = registerCopilotActionHandler('b601_run_recover', async () => {
      logActivity('recover')
      setRecovering(true)
      await b601Recover()
      setRecovering(false)
      await pollHealth()
    })
    const u3 = registerCopilotActionHandler('b601_install_local_agent', () => {
      window.location.href = '/setup'
    })
    return () => { u1(); u2(); u3() }
  }, [pollHealth, logActivity])

  const step = state.currentStep

  if (step === 'connect') {
    return (
      <>
        <B601EmergencyBar running={teleopRunning} stopping={stopping} onStop={() => void stopTeleop()} />
        <SetupStepCard
        stepId="connect"
        title={steps[0].label}
        description={steps[0].shortHint}
        nextDisabled={connecting || !isB601HardwareReady(health)}
        nextLabel={isB601HardwareReady(health) ? '下一步：试遥操' : '下一步：了解遥操'}
      >
        <p className="text-sm text-muted-foreground">
          先在下方面板拖滑条，看 3D 机械臂怎么动（没真机也能玩）。接好 PCAN 和主臂后，在下方输入本机密码连接从臂。
        </p>
        <B601Stage
          health={health}
          recovering={recovering || connecting}
          teleopRunning={teleopRunning}
          playJoints={stagePlayJoints}
        />
        <B601JointPlayPanel
          onChange={setPlayPose}
          hardwareReady={isB601HardwareReady(health)}
          canLinked={health?.can_up ?? false}
          teleopRunning={teleopRunning}
        />
        {connecting && (
          <p className="flex items-center gap-2 text-sm text-sky-200/90">
            <Loader2 className="h-4 w-4 animate-spin" />
            正在连接…
          </p>
        )}
        {msg && !connecting && !isB601HardwareReady(health) && (
          <p className="text-sm text-amber-200/90">{msg}</p>
        )}
        {health?.power_hint && <p className="text-sm text-amber-400">{health.power_hint}</p>}
        <B601ConnectPanel
          health={health}
          onHealth={(h) => {
            setHealth(h)
            if (isB601HardwareReady(h)) markComplete('connect', true)
            if (h.issues.length) setMsg(h.issues.join(' · '))
            else setMsg(null)
          }}
          onActivity={(k) => logActivity(k as 'health_poll' | 'recover')}
        />
        <B601CalibrationPanel
          hardwareReady={isB601HardwareReady(health)}
          calibrateRunning={calibrateRunning}
          calibrateTarget={calibrateTarget}
          calibrateLog={calibrateLog}
          busy={busy}
          onCalibrateChange={() => void pollHealth()}
        />
        <B601ActivityPanel entries={activity} />
      </SetupStepCard>
      </>
    )
  }

  if (step === 'teleop') {
    const checkAlignment = async () => {
      setCheckingAlignment(true)
      setMsg(null)
      setAlignment(null)
      setAlignmentHint('请勿同时点「读取从臂」或其他按钮')
      try {
        const cfg = await getB601Config()
        setAlignment(await b601TeleopAlignment({ robotId: cfg.robot_id, leaderId: cfg.leader_id }))
      } catch (e) {
        setMsg(e instanceof Error ? e.message : '对齐检查失败')
      } finally {
        setCheckingAlignment(false)
        setAlignmentHint(null)
      }
    }

    return (
      <>
        <B601EmergencyBar running={teleopRunning} stopping={stopping} onStop={() => void stopTeleop()} />
        <SetupStepCard
          stepId="teleop"
          title={steps[1].label}
          description={steps[1].shortHint}
          hideNext
        >
          <B601Stage health={health} recovering={recovering} teleopRunning={teleopRunning} playJoints={stagePlayJoints} />
          <div className="rounded-lg border border-white/10 bg-black/20 p-3 space-y-2">
            <p className="text-sm font-medium">什么是遥操？</p>
            <p className="text-sm text-muted-foreground leading-relaxed">
              遥操 = 你动手<strong className="font-normal text-foreground/90">主臂</strong>，从臂会跟着做同样动作。
              已连接真机时，可直接点<strong className="font-normal text-foreground/90">「开始遥操」</strong>（与 Seeed 官方一致）；
              「检查对齐」是可选安全步骤，读不到角度也不影响启动。
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              disabled={teleopRunning}
              onClick={async () => {
                setBusy(true)
                setMsg(null)
                try {
                  setTeleopPhase('正在连接从臂…')
                  logActivity('teleop_start')
                  const s = await b601OneClickTeleopStart({
                    onPhase: (msg) => setTeleopPhase(msg),
                  })
                  if (s?.running && s?.healthy !== false) setTeleopRunning(true)
                  else if (s?.last_error) setMsg(s.last_error)
                  setAlignment(null)
                } catch (e) {
                  if (e instanceof B601ArmsNotAlignedError) {
                    setAlignment(e.alignment)
                    setMsg(e.message)
                  } else {
                    setMsg(e instanceof Error ? e.message : '遥操启动失败')
                  }
                } finally {
                  setBusy(false)
                  setTeleopPhase(null)
                  void pollTeleop()
                }
              }}
            >
              {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              开始遥操
            </Button>
            <Button
              variant="outline"
              disabled={busy || teleopRunning || checkingAlignment}
              onClick={() => void checkAlignment()}
            >
              {checkingAlignment ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              检查对齐（可选）
            </Button>
          </div>
          <B601AlignmentPanel
            alignment={alignment}
            checking={checkingAlignment}
            checkingHint={alignmentHint}
            onRecheck={() => void checkAlignment()}
            forceBusy={busy}
          />
          {teleopPhase && (
            <p className="flex items-center gap-2 text-sm text-amber-200/90">
              <Loader2 className="h-4 w-4 animate-spin shrink-0" />
              {teleopPhase}
            </p>
          )}
          {teleopRunning ? (
            <Button variant="destructive" disabled={stopping} onClick={() => void stopTeleop()}>
              {teleopPhase === '卸力中…' ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Square className="mr-2 h-4 w-4 fill-current" />
              )}
              {teleopPhase === '卸力中…' ? '卸力中…' : '停止遥操'}
            </Button>
          ) : null}
          {teleopRunning && (
            <p className="text-sm text-emerald-400">遥操运行中 — 请缓慢移动主臂，观察从臂是否跟随</p>
          )}
          {teleopTested && !teleopRunning && (
            <Button variant="outline" onClick={() => goNext()}>
              继续：录示教
            </Button>
          )}
          <B601ConnectPanel
            health={health}
            onHealth={(h) => {
              setHealth(h)
              if (isB601HardwareReady(h)) markComplete('connect', true)
            }}
            onActivity={(k) => logActivity(k as 'health_poll' | 'recover')}
            compact
          />
          {msg && <p className="text-sm text-destructive">{msg}</p>}
          <B601ActivityPanel entries={activity} />
        </SetupStepCard>
      </>
    )
  }

  if (step === 'record') {
    return (
      <>
        <B601EmergencyBar
          running={teleopRunning || recordRunning}
          stopping={stopping}
          onStop={() => void stopTeleop()}
        />
        <SetupStepCard
          stepId="record"
          title={steps[2].label}
          description="官方 lerobot-record，数据格式与 SO-101 相同（HF owner/name）。采完再进训练。"
          nextDisabled={!state.completed.record}
          onNext={goNext}
        >
          <B601RecordTab
            camerasAvailable={health?.cameras_available ?? 0}
            cameraPrefs={loadB601CameraPrefs()}
            teleopRunning={teleopRunning}
            repoPrefix={repoPrefix}
            lastDatasetId={state.lastDatasetId}
            hideSnapshot
            onRunningChange={setRecordRunning}
            onDatasetReady={(id) => {
              setLastDataset(id)
              markComplete('record', true)
              logActivity('record_start')
            }}
          />
          {state.completed.record && (
            <Button className="mt-3" onClick={() => goNext()}>
              继续：训练
            </Button>
          )}
          {msg && <p className="text-sm text-destructive">{msg}</p>}
        </SetupStepCard>
      </>
    )
  }

  const trainHref = state.lastDatasetId
    ? `/training?dataset_id=${encodeURIComponent(state.lastDatasetId)}&algorithm=act&from_setup=1&runtime=b601_rs`
    : '/training?runtime=b601_rs'

  return (
    <SetupStepCard stepId="run" title={steps[3].label} description={steps[3].shortHint} hideNext>
      <p className="text-sm text-muted-foreground">
        数据已按官方 LeRobot 格式落盘
        {state.lastDatasetId ? (
          <>
            ：<code className="font-mono text-xs">{state.lastDatasetId}</code>
          </>
        ) : null}
        。去训练页发起 ACT；模型就绪后在工作台「动作」Tab 部署。
      </p>
      <div className="flex flex-wrap gap-2">
        <Link to={trainHref} className="inline-flex h-9 items-center rounded-md border px-4 text-sm">
          {state.lastDatasetId ? '用这份数据训练' : '打开训练页'}
        </Link>
        <Button
          onClick={() => {
            markComplete('run', true)
            onBackToWorkspace()
          }}
        >
          去工作台
        </Button>
      </div>
    </SetupStepCard>
  )
}

function B601DailyConsole() {
  const { token } = useAuth()
  const [health, setHealth] = useState<B601Health | null>(null)
  const [tab, setTab] = useState<B601Tab>('teleop')
  const [busy, setBusy] = useState(false)
  const [stopping, setStopping] = useState(false)
  const [recovering, setRecovering] = useState(false)
  const [teleopRunning, setTeleopRunning] = useState(false)
  const [teleopStarting, setTeleopStarting] = useState(false)
  const [teleopHealthy, setTeleopHealthy] = useState(true)
  const [recordRunning, setRecordRunning] = useState(false)
  const [lastRecordDataset, setLastRecordDataset] = useState<string | null>(null)
  const [inferenceRunning, setInferenceRunning] = useState(false)
  const [calibrateRunning, setCalibrateRunning] = useState(false)
  const [calibrateTarget, setCalibrateTarget] = useState<string | null>(null)
  const [calibrateLog, setCalibrateLog] = useState<string[]>([])
  const [cameraPrefs, setCameraPrefs] = useState<B601CameraPrefs>(() => loadB601CameraPrefs())
  const [useCameras, setUseCameras] = useState(false)
  const [policyPath, setPolicyPath] = useState('')
  const [deploying, setDeploying] = useState(false)
  const [deployError, setDeployError] = useState<string | null>(null)
  const [recentJobs, setRecentJobs] = useState<TrainingJobDTO[]>([])
  const [pipUrl, setPipUrl] = useState<string | null>(null)
  const [pipBroken, setPipBroken] = useState(false)
  const [logTail, setLogTail] = useState<string[]>([])
  const [connecting, setConnecting] = useState(true)
  const [playPose, setPlayPose] = useState(b601DefaultJointPose)
  const [motorZeroBaseline, setMotorZeroBaseline] = useState<Record<string, number> | null>(null)
  const [gravityCompRunning, setGravityCompRunning] = useState(false)
  const playUrdfJoints = useMemo(() => b601JointsToUrdf(playPose), [playPose])
  const [alignment, setAlignment] = useState<B601Alignment | null>(null)
  const [checkingAlignment, setCheckingAlignment] = useState(false)
  const [alignmentHint, setAlignmentHint] = useState<string | null>(null)
  const [ros2Bringup, setRos2Bringup] = useState(false)
  const [playbackJoints, setPlaybackJoints] = useState<Record<string, number> | null>(null)
  const [playbackActive, setPlaybackActive] = useState(false)
  const [recordCoachLine, setRecordCoachLine] = useState<string | null>(null)
  const { entries: activity, log: logActivity } = useB601Activity()

  const poll = useCallback(async () => {
    try {
      const h = await refreshB601Health({
        skipAutoProbe: busy || checkingAlignment || teleopRunning || stopping,
      })
      setHealth(h)
      const ts = await b601TeleopStatus()
      setTeleopRunning(Boolean(ts.running && ts.healthy !== false))
      setTeleopStarting(Boolean(ts.starting && !ts.running))
      setTeleopHealthy(ts.healthy !== false)
      const rs = await b601RecordStatus()
      setRecordRunning(rs.running)
      if (!rs.running && rs.returncode === 0 && rs.repo_id) {
        setLastRecordDataset(rs.repo_id)
      }
      const cs = await b601CalibrateStatus()
      setCalibrateRunning(cs.running)
      setCalibrateTarget(cs.calibrate_target ?? null)
      setCalibrateLog(cs.log_tail)
      const inf = await b601InferenceStatus()
      setInferenceRunning(inf.running)
      if (!inf.running && inf.last_error) {
        setDeployError(inf.last_error)
      } else if (inf.running) {
        setDeployError(null)
      }
      setLogTail([...ts.log_tail, ...rs.log_tail, ...(inf.log_tail || [])])
    } catch {
      /* agent offline */
    } finally {
      setConnecting(false)
    }
  }, [busy, checkingAlignment, teleopRunning, stopping])

  useEffect(() => {
    if (!token) return
    void authJson<{ items: TrainingJobDTO[] }>('/api/v1/trainings')
      .then((r) => setRecentJobs(r.items ?? []))
      .catch(() => {
        /* 未登录或 token 过期 — 工作台不展示训练历史即可 */
      })
  }, [token])

  useEffect(() => {
    setConnecting(true)
    void poll()
    // Without CAN (Windows demo), poll slowly — status endpoints are no-ops but still load the agent.
    const noCan = health != null && !health.can_present
    const intervalMs = teleopRunning ? 8000 : noCan ? 12000 : 3000
    const t = setInterval(() => void poll(), intervalMs)
    return () => clearInterval(t)
  }, [poll, teleopRunning, health?.can_present])

  const { joints: liveJoints } = useB601LiveJoints(teleopRunning)
  const { motorJoints: gcMotorJoints } = useB601GravityCompLiveJoints(gravityCompRunning)
  const liveUrdfJoints = useMemo(() => b601JointsToUrdf(liveJoints), [liveJoints])
  const gcDisplayJoints = useMemo(
    () => b601MotorJointsForViewer(gcMotorJoints, motorZeroBaseline),
    [gcMotorJoints, motorZeroBaseline],
  )
  const gcUrdfJoints = useMemo(() => b601JointsToUrdf(gcDisplayJoints), [gcDisplayJoints])
  const playbackUrdfJoints = useMemo(() => b601JointsToUrdf(playbackJoints), [playbackJoints])
  const hasPlaybackPose = Boolean(playbackJoints && Object.keys(playbackJoints).length >= 3)
  const stagePlayJoints = teleopRunning
    ? liveUrdfJoints
    : hasPlaybackPose && playbackUrdfJoints
      ? playbackUrdfJoints
      : gravityCompRunning
        ? (gcUrdfJoints ?? playUrdfJoints)
        : playUrdfJoints
  const jointHud = teleopRunning
    ? liveJoints
    : hasPlaybackPose
      ? playbackJoints
      : gravityCompRunning
        ? gcDisplayJoints
        : null
  const stageFocus: B601StageFocus = recordRunning
    ? 'record'
    : teleopRunning
      ? 'teleop'
      : hasPlaybackPose || playbackActive
        ? 'playback'
        : 'idle'
  const mirrorForSliders = teleopRunning
    ? liveJoints
    : hasPlaybackPose
      ? playbackJoints
      : gravityCompRunning
        ? gcDisplayJoints
        : null

  useEffect(() => {
    void b601GravityCompStatus()
      .then((s) => setGravityCompRunning(Boolean(s.running)))
      .catch(() => {})
  }, [])

  useEffect(() => {
    const u1 = registerCopilotActionHandler('b601_run_health_check', async () => { await poll() })
    const u2 = registerCopilotActionHandler('b601_run_recover', async () => {
      logActivity('recover')
      setRecovering(true)
      await b601Recover()
      setRecovering(false)
      await poll()
    })
    const u3 = registerCopilotActionHandler('b601_install_local_agent', () => {
      window.location.href = '/setup'
    })
    return () => { u1(); u2(); u3() }
  }, [poll, logActivity])

  const wrap = async (fn: () => Promise<void>) => {
    setBusy(true)
    try {
      await fn()
      await poll()
    } finally {
      setBusy(false)
    }
  }

  const checkAlignment = async () => {
    setCheckingAlignment(true)
    setAlignment(null)
    setAlignmentHint('请勿同时点「读取从臂」或其他按钮')
    try {
      const cfg = await getB601Config()
      setAlignment(await b601TeleopAlignment({ robotId: cfg.robot_id, leaderId: cfg.leader_id }))
    } catch (e) {
      setAlignmentHint(e instanceof Error ? e.message : '对齐检查失败')
    } finally {
      setCheckingAlignment(false)
      setAlignmentHint(null)
    }
  }

  const startTeleop = () =>
    wrap(async () => {
      logActivity('teleop_start')
      try {
        const s = await b601OneClickTeleopStart({
          useCameras,
          cameraIndices: cameraPrefs.indices,
        })
        if (s?.running && s?.healthy !== false) setTeleopRunning(true)
        setAlignment(null)
      } catch (e) {
        if (e instanceof B601ArmsNotAlignedError) {
          setAlignment(e.alignment)
        } else {
          throw e
        }
      } finally {
        setRecovering(false)
      }
    })

  const forceStartTeleop = () =>
    wrap(async () => {
      if (!window.confirm('强制启动：从臂可能猛窜。确认周围无人、已做好急停准备？')) return
      logActivity('teleop_start')
      const s = await b601TeleopStartWithConfirm({
        useCameras,
        cameraIndices: cameraPrefs.indices,
        force: true,
        skipConfirm: true,
      })
      if (s) {
        setTeleopRunning(true)
        setAlignment(null)
      }
    })

  const stopTeleop = async () => {
    if (stopping) return
    setStopping(true)
    setTeleopRunning(false)
    logActivity('teleop_stop')
    try {
      await b601TeleopStopSafe()
    } finally {
      setStopping(false)
      void poll()
    }
  }

  const emergencyStopInference = async () => {
    if (stopping) return
    setStopping(true)
    setInferenceRunning(false)
    setDeploying(false)
    logActivity('disable')
    try {
      await b601InferenceStopSafe()
      setDeployError(null)
    } finally {
      setStopping(false)
      void poll()
    }
  }

  return (
    <div className="space-y-4">
      <B601EmergencyBar
        running={inferenceRunning || teleopRunning}
        stopping={stopping}
        mode={inferenceRunning ? 'inference' : 'teleop'}
        onStop={() => void (inferenceRunning ? emergencyStopInference() : stopTeleop())}
      />
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[hsl(var(--primary))]/15">
          <Bot className="h-5 w-5 text-[hsl(var(--primary))]" />
        </div>
        <div>
          <h2 className="text-lg font-semibold">工作台</h2>
          <p className="text-xs text-muted-foreground">遥操 · 录数据 · 部署</p>
        </div>
      </div>

      <div
        className={`grid gap-4 lg:items-start ${
          recordRunning || tab === 'record' || hasPlaybackPose
            ? 'lg:grid-cols-[minmax(0,0.95fr)_minmax(340px,1.05fr)]'
            : 'lg:grid-cols-[1fr_380px]'
        }`}
      >
        <div className="space-y-3 lg:sticky lg:top-3 lg:self-start">
          <B601Stage
            health={health}
            teleopRunning={teleopRunning}
            gravityCompRunning={gravityCompRunning}
            focus={stageFocus}
            compact={recordRunning || hasPlaybackPose || playbackActive}
            cameraPreviewUrl={pipUrl}
            pipBroken={pipBroken}
            onPipError={() => setPipBroken(true)}
            onPipLoad={() => setPipBroken(false)}
            recovering={recovering || connecting}
            playJoints={stagePlayJoints}
            jointHud={jointHud}
            onMeshFailed={(url) => logActivity('urdf_mesh_fail', url)}
            recordCoachLine={recordCoachLine}
          />
          <B601JointPlayPanel
            onChange={setPlayPose}
            hardwareReady={isB601HardwareReady(health)}
            canLinked={health?.can_up ?? false}
            teleopRunning={teleopRunning}
            gravityCompRunning={gravityCompRunning}
            mirrorJoints={mirrorForSliders}
            onMotorBaseline={setMotorZeroBaseline}
            collapsed={recordRunning || tab === 'record' || hasPlaybackPose}
          />
          {!recordRunning && !hasPlaybackPose && tab !== 'record' && (
            <B601ConnectPanel
              health={health}
              onHealth={setHealth}
              onActivity={(k) => logActivity(k as 'health_poll' | 'recover')}
              compact
            />
          )}
        </div>
        {connecting && (
          <p className="absolute top-20 left-4 z-20 flex items-center gap-2 rounded-md bg-sky-950/90 px-3 py-1.5 text-xs text-sky-100">
            <Loader2 className="h-3 w-3 animate-spin" />
            正在配置 CAN 并扫描从臂…
          </p>
        )}
        <div className="min-h-0 space-y-3 lg:max-h-[calc(100vh-7.5rem)] lg:overflow-y-auto">
          {!recordRunning && !teleopRunning && !hasPlaybackPose && tab !== 'record' && (
            <B601ActivityPanel entries={activity} />
          )}
          <B601SidebarTabs
            activeTab={tab}
            onTabChange={setTab}
            teleopPanel={
              <>
              <B601TeleopTab
                teleopRunning={teleopRunning}
                teleopStarting={teleopStarting}
                teleopHealthy={teleopHealthy}
                recordRunning={recordRunning}
                busy={busy}
                stopping={stopping}
                browseMode={isB601BrowseOnly(health)}
                needsCalibration={isB601HardwareReady(health) && !isB601ReadyForTeleop(health)}
                activeRobotId={health?.robot_id}
                activeLeaderId={health?.leader_id}
                useCameras={useCameras}
                cameraLabel={
                  `正面 Cam ${cameraPrefs.front} · 侧面 Cam ${cameraPrefs.side}` +
                  (cameraPrefs.top == null ? '' : ` · 顶部 Cam ${cameraPrefs.top}`)
                }
                onUseCamerasChange={setUseCameras}
                alignment={alignment}
                checkingAlignment={checkingAlignment}
                alignmentHint={alignmentHint}
                onCheckAlignment={() => void checkAlignment()}
                onForceStart={forceStartTeleop}
                logTail={logTail}
                onStartTeleop={startTeleop}
                onStopTeleop={() => void stopTeleop()}
                onRestartTeleop={startTeleop}
              />
              <B601GravityCompPanel
                busy={busy}
                teleopRunning={teleopRunning}
                canLinked={health?.can_up ?? false}
                onBusy={setBusy}
                onRunningChange={setGravityCompRunning}
                onMotorBaseline={setMotorZeroBaseline}
                onDisplayJoints={setPlayPose}
              />
              {isB601HardwareReady(health) && !isB601ReadyForTeleop(health) && (
                <B601CalibrationPanel
                  hardwareReady
                  calibrateRunning={calibrateRunning}
                  calibrateTarget={calibrateTarget}
                  calibrateLog={calibrateLog}
                  busy={busy}
                  onCalibrateChange={() => void poll()}
                />
              )}
              </>
            }
            visionPanel={
              <B601VisionTab
                active={tab === 'vision'}
                onPreviewChange={setPipUrl}
                onPrefsChange={setCameraPrefs}
              />
            }
            recordPanel={
              <B601RecordTab
                camerasAvailable={health?.cameras_available ?? 0}
                cameraPrefs={cameraPrefs}
                teleopRunning={teleopRunning}
                repoPrefix={health?.arm_variant === 'dm' ? 'b601-dm' : 'b601-rs'}
                lastDatasetId={lastRecordDataset}
                onRunningChange={setRecordRunning}
                onDatasetReady={(id) => {
                  setLastRecordDataset(id)
                  logActivity('record_start')
                }}
                onPlaybackJoints={setPlaybackJoints}
                onPlaybackActiveChange={setPlaybackActive}
                onCoachLine={setRecordCoachLine}
                onSnapshot={(repo) =>
                  wrap(async () => {
                    await b601Snapshot({ repo_id: repo, label: repo.split('/').pop()?.slice(0, 32) || 'lab' })
                  })
                }
              />
            }
            motionPanel={
              <B601MotionTab
                policyPath={policyPath}
                onPolicyPathChange={setPolicyPath}
                deploying={deploying}
                inferenceRunning={inferenceRunning}
                deployError={deployError}
                recentJobs={recentJobs}
                cameraPrefs={cameraPrefs}
                onGoVision={() => setTab('vision')}
                onDeploy={(cameraIndices) =>
                  wrap(async () => {
                    setDeploying(true)
                    setDeployError(null)
                    try {
                      const r = await b601InferenceStart(policyPath, undefined, {
                        backend: 'remote',
                        cameraIndices,
                      })
                      setInferenceRunning(Boolean(r.running))
                      if (!r.running && r.last_error) setDeployError(r.last_error)
                    } catch (e) {
                      setInferenceRunning(false)
                      setDeployError(e instanceof Error ? e.message : '部署失败')
                    } finally {
                      setDeploying(false)
                    }
                  })
                }
                onStopInference={() => void emergencyStopInference()}
              />
            }
            advancedPanel={
              <>
              <p className="text-[11px] leading-relaxed text-muted-foreground">
                「自动到位」：让手臂自动走到某个姿势，给调试用。日常遥操 / 录数据 / 部署一般不用。
              </p>
              <B601KinematicsTab
                teleopRunning={teleopRunning}
                recordRunning={recordRunning}
                busy={busy}
                onBusy={setBusy}
                onPreviewJoints={setPlayPose}
                ros2BringupRunning={ros2Bringup}
              />
              <div className="border-t border-white/10 pt-3">
                <B601AdvancedDrawer
                  busy={busy}
                  calibrateRunning={calibrateRunning}
                  calibrateTarget={calibrateTarget}
                  calibrateLog={calibrateLog}
                  onRecover={() =>
                    wrap(async () => {
                      logActivity('recover')
                      setRecovering(true)
                      await b601Recover()
                      setRecovering(false)
                    })
                  }
                  onDisable={() =>
                    wrap(async () => {
                      logActivity('disable')
                      await b601Disable()
                    })
                  }
                  onCalibrateStart={(target) =>
                    wrap(async () => {
                      logActivity('calibrate_start', target)
                      await b601CalibrateStart(target)
                    })
                  }
                  onCalibrateContinue={() => wrap(async () => { await b601CalibrateContinue() })}
                  onCalibrateStop={() => wrap(async () => { await b601CalibrateStop() })}
                />
              </div>
              {isB601HardwareReady(health) && (
                <div className="border-t border-white/10 pt-3">
                  <p className="mb-2 text-xs font-medium text-muted-foreground">日常重标定</p>
                  <B601CalibrationPanel
                    hardwareReady
                    calibrateRunning={calibrateRunning}
                    calibrateTarget={calibrateTarget}
                    calibrateLog={calibrateLog}
                    busy={busy}
                    onCalibrateChange={() => void poll()}
                  />
                </div>
              )}
              <B601Ros2Panel
                busy={busy}
                teleopRunning={teleopRunning}
                onBusy={setBusy}
                onBringupChange={setRos2Bringup}
              />
              </>
            }
          />
        </div>
      </div>
    </div>
  )
}

function B601WizardShell({ onBackToWorkspace }: { onBackToWorkspace: () => void }) {
  return (
    <SetupProvider runtimeId="b601_rs">
      <div className="py-2">
        <p className="mb-4 text-xs text-muted-foreground">
          可选：分步检查连接 → 试遥操 → 录数据。日常直接用「工作台」，不必走完每一步。
        </p>
        <div className="grid gap-6 lg:grid-cols-[280px_1fr]">
          <SetupSidebar />
          <B601WizardBody onBackToWorkspace={onBackToWorkspace} />
        </div>
      </div>
    </SetupProvider>
  )
}

type B601PageTab = 'workspace' | 'onboarding'

export function RobotB601() {
  const [searchParams] = useSearchParams()
  const [pageTab, setPageTab] = useState<B601PageTab>('onboarding')
  const [teleopRunning, setTeleopRunning] = useState(false)
  const [teleopStarting, setTeleopStarting] = useState(false)
  const [busy, setBusy] = useState(false)
  const [connectionHealth, setConnectionHealth] = useState<B601Health | null>(null)
  // Variant: which B601 hardware the user has. Persisted in localStorage so the
  // choice survives reloads. The backend gets notified via setB601Config.
  type B601Variant = 'rs' | 'dm' | 'bi_dm'
  const [variant, setVariant] = useState<B601Variant>(() => {
    const saved = typeof window !== 'undefined' ? window.localStorage.getItem('b601.variant') : null
    if (saved === 'dm' || saved === 'bi_dm') return saved
    // Auto-pick from backend health if available.
    return 'rs'
  })
  const [variantSaving, setVariantSaving] = useState(false)
  const [variantError, setVariantError] = useState<string | null>(null)

  const onPickVariant = useCallback(async (v: B601Variant) => {
    if (v === variant) return
    setVariant(v)
    setVariantError(null)
    try {
      window.localStorage.setItem('b601.variant', v)
    } catch {
      /* ignore */
    }
    // Backend only knows 'rs' | 'dm' (bi_dm is a UI concept for now; backend
    // treats it as 'dm' until a dedicated dual-arm runtime lands).
    setVariantSaving(true)
    try {
      await setB601Config({ arm_variant: v === 'rs' ? 'rs' : 'dm' })
    } catch (e) {
      setVariantError(e instanceof Error ? e.message : '保存机型失败')
    } finally {
      setVariantSaving(false)
    }
  }, [variant])

  const pollConnection = useCallback(async () => {
    try {
      // skipAutoProbe: shell poll must stay cheap (Windows demo has no CAN).
      setConnectionHealth(await refreshB601Health({ skipAutoProbe: true }))
    } catch {
      setConnectionHealth(null)
    }
  }, [])

  useEffect(() => {
    void pollConnection()
    // Slow shell poll — workspace/wizard already poll; avoid stacking 5s+3s+2s.
    const t = setInterval(() => void pollConnection(), 15000)
    return () => clearInterval(t)
  }, [pollConnection])

  const pollTeleopGlobal = useCallback(async () => {
    try {
      const s = await b601TeleopStatus()
      setTeleopRunning(s.running)
      setTeleopStarting(Boolean(s.starting && !s.running))
    } catch {
      setTeleopRunning(false)
      setTeleopStarting(false)
    }
  }, [])

  useEffect(() => {
    if (searchParams.get('tab') === 'workspace') setPageTab('workspace')
  }, [searchParams])

  useEffect(() => {
    void pollTeleopGlobal()
    // No CAN on Windows demo — don't hammer teleop/status every 2s.
    const noCan = connectionHealth != null && !connectionHealth.can_present
    const intervalMs = noCan ? 15000 : 4000
    const t = setInterval(() => void pollTeleopGlobal(), intervalMs)
    return () => clearInterval(t)
  }, [pollTeleopGlobal, connectionHealth])

  const stopTeleopGlobal = useCallback(async () => {
    if (busy) return
    setBusy(true)
    setTeleopRunning(false)
    try {
      await b601TeleopStopSafe()
    } finally {
      setBusy(false)
      try {
        const s = await b601TeleopStatus()
        setTeleopRunning(Boolean(s.running && s.healthy !== false))
      } catch {
        setTeleopRunning(false)
      }
    }
  }, [busy])

  return (
    <div className="container mx-auto px-4 py-6">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Bot className="h-6 w-6 text-primary" />
        <h1 className="text-xl font-semibold">reBot B601</h1>
        <Badge
          variant="outline"
          className={
            isB601ReadyForTeleop(connectionHealth)
              ? 'border-green-500/40 text-green-400'
              : isB601HardwareReady(connectionHealth)
                ? 'border-amber-500/40 text-amber-300'
                : 'border-sky-500/40 text-sky-300'
          }
        >
          {isB601ReadyForTeleop(connectionHealth)
            ? '已连接'
            : isB601HardwareReady(connectionHealth)
              ? '待标定'
              : '浏览模式'}
        </Badge>
        <div className="ml-auto flex gap-1 rounded-lg border border-white/10 p-0.5">
          <Button
            size="sm"
            variant={pageTab === 'onboarding' ? 'default' : 'ghost'}
            onClick={() => setPageTab('onboarding')}
          >
            新手上手
          </Button>
          <Button
            size="sm"
            variant={pageTab === 'workspace' ? 'default' : 'ghost'}
            onClick={() => setPageTab('workspace')}
          >
            工作台
          </Button>
        </div>
        <Link to="/robots" className="inline-flex h-8 items-center gap-1 rounded-md px-3 text-xs hover:bg-accent">
          <ArrowLeft className="h-4 w-4" />
          机器人列表
        </Link>
      </div>

      {/* Variant picker — first thing the user sees, so they don't have to guess. */}
      <div className="mb-4 rounded-lg border border-white/10 bg-[hsl(var(--muted))]/20 px-4 py-3">
        <div className="flex flex-wrap items-center gap-3">
          <div className="min-w-0 flex-1">
            <p className="text-xs font-medium">你的 B601 是哪种？</p>
            <p className="mt-0.5 text-[11px] text-muted-foreground">
              看电机型号选一个。选错也没事，随时可以换。
            </p>
          </div>
          <div className="flex flex-wrap gap-1 rounded-lg border border-white/10 p-0.5">
            {([
              { id: 'rs', label: 'RS · RobStride', hint: 'CAN 总线（PCAN / SocketCAN）' },
              { id: 'dm', label: 'DM · 达妙 Damiao', hint: 'USB-CAN 串口桥（4340P/4310）' },
              { id: 'bi_dm', label: 'DM 双臂', hint: '两只 DM 从臂 + 两只主臂' },
            ] as { id: B601Variant; label: string; hint: string }[]).map((opt) => (
              <button
                key={opt.id}
                type="button"
                onClick={() => void onPickVariant(opt.id)}
                className={
                  'rounded-md px-3 py-1.5 text-xs transition ' +
                  (variant === opt.id
                    ? 'bg-[hsl(var(--primary))] text-primary-foreground'
                    : 'text-muted-foreground hover:bg-white/5')
                }
                title={opt.hint}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>
        {variantSaving ? (
          <p className="mt-2 text-[11px] text-sky-300">正在保存机型…</p>
        ) : null}
        {variantError ? (
          <p className="mt-2 text-[11px] text-amber-300">机型已记到本机，但保存到机器人失败：{variantError}</p>
        ) : null}
      </div>

      {pageTab === 'workspace' ? (
        <B601DailyConsole />
      ) : (
        <B601WizardShell onBackToWorkspace={() => setPageTab('workspace')} />
      )}

      {pageTab === 'onboarding' && teleopRunning && (
        <B601EmergencyBar running={teleopRunning} stopping={busy} onStop={() => void stopTeleopGlobal()} />
      )}

      <CommunityResources
        intro="reBot B601 是 Seeed Studio 的 CAN 总线机械臂。内容以官方产出为主，遇到问题先查 Seeed wiki 与论坛。"
        docs={[
          { label: 'Seeed 中文入门（B601-RS + LeRobot）', url: 'https://wiki.seeedstudio.com/cn/rebot_arm_b601_rs_lerobot/' },
          { label: 'Seeed GitHub（lerobot-robot-seeed-b601）', url: 'https://github.com/Seeed-Projects/lerobot-robot-seeed-b601' },
        ]}
        communities={[
          { label: 'Seeed Discord', url: 'https://discord.seeed.cc' },
          { label: 'Seeed 论坛', url: 'https://forum.seeedstudio.com/' },
        ]}
        faqs={[
          {
            q: '预组装套件需要重新写电机 ID 吗？',
            a: '不要。成品套件只扫描 1–7 号电机确认在线即可，重写 ID 是常见翻车点（与平台 AGENTS.md 纪律一致）。',
          },
          {
            q: 'LeRobot 里用不了 RS 变体？',
            a: 'RS 变体在 LeRobot 的 seeed_b601_rs_follower 仍标注 "still being refined"，robstride CAN adapter 尚未接入——wiki 走的是 socketcan（can0）路径，先确认你的版本。',
          },
          {
            q: 'CAN 总线起不来？',
            a: '必须按顺序：sudo ip link set can0 type can bitrate 1000000 restart-ms 100 再 up。报错先查 can0 是否真的起来了。',
          },
          {
            q: '校准/遥操作直接失败？',
            a: '检查电机 ID 映射是否与默认表一致（0x01–0x07 master / 0x11–0x17 feedback），不一致必失败。',
          },
          {
            q: '操作前要做什么？',
            a: '先做零位校准（零位 = 夹爪全闭）；严禁热插拔 XT30 电机电源（wiki 安全警告）。',
          },
        ]}
      />
    </div>
  )
}