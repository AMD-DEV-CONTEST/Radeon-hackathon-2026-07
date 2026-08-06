/**
 * Required teleoperation dry run before data recording.
 *
 * 目标：用户在当前页面里，一键把主控臂→执行臂链路跑起来，手动晃主控臂，
 * 在旁边的小 URDF viewer 里看到执行臂关节同步变化。不跳外部页面、
 * 不需要命令行、不需要用户理解 /ws/teleop 和 /ws/ui。
 *
 * 工作流：
 *   1. 从连接阶段拿到主控臂 / 执行臂端口。
 *   2. 用户点"开始遥操作" → POST /api/teleop/start 启动两个 sender 子进程。
 *   3. 同时连上 /ws/ui，把实时关节数据灌进 UrdfViewer。
 *   4. 后台检测"有没有持续的关节变化"：只要某关节的 rad 在最近 3 秒内
 *      累计变化 ≥ 0.08 rad（~4.6°），就把"下一步"按钮点亮，提示用户。
 *   5. 用户自己确认"我看到执行臂跟着动了" → 点"下一步"。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertTriangle,
  CircleDot,
  Loader2,
  Play,
  Square,
  Activity,
  Hand,
  Unlock,
  ScanLine,
} from 'lucide-react'
import { Button } from '../../ui/button'
import { UrdfViewer } from '../../features/UrdfViewer'
import { cn } from '../../../lib/utils'
import { agentFetch } from '../../../lib/localAgent'
import { JOINT_NAMES, type JointMap } from '../../../types/botclaw'
import { useTeleopWebSocket } from '../../../hooks/useTeleopWebSocket'
import { SetupStepCard } from '../SetupStepCard'
import { useSetup } from '../SetupProvider'

interface ProcessStatus {
  role: string
  alive: boolean
  pid: number | null
  returncode: number | null
  stderr_tail: string[]
}

interface SessionStatus {
  running: boolean
  session_id?: string | null
  leader_port?: string | null
  follower_port?: string | null
  started_at?: number | null
  uptime_s?: number | null
  processes?: ProcessStatus[]
}

interface AlignmentMismatch {
  motor: string
  delta_pct: number
  delta_deg: number
  hint: string
}

interface AlignmentReport {
  ok: boolean
  tolerance: number
  mismatches: AlignmentMismatch[]
  skipped?: boolean
}

// 关节中文名（UI 显示），后端 motor 名 → 中文
const MOTOR_LABELS_ZH: Record<string, string> = {
  shoulder_pan: '肩旋（J1）',
  shoulder_lift: '肩抬（J2）',
  elbow_flex: '肘弯（J3）',
  wrist_flex: '腕俯仰（J4）',
  wrist_roll: '腕旋（J5）',
  gripper: '夹爪（J6）',
}

const EMPTY_JOINTS: JointMap = { '1': 0, '2': 0, '3': 0, '4': 0, '5': 0, '6': 0 }
// Motion threshold: cumulative |Δrad| in the last window, summed across joints,
// before we consider the chain "actually wiggling". Tuned for sts3215 noise
// floor (~0.002 rad jitter per joint at rest).
const MOTION_WINDOW_MS = 3000
const MOTION_THRESHOLD_RAD = 0.08

export function Step3Teleop() {
  const { state, markComplete, goNext } = useSetup()
  const leaderPort = state.leaderPort?.port ?? null
  const followerPort = state.followerPort?.port ?? null

  const [session, setSession] = useState<SessionStatus | null>(null)
  const [starting, setStarting] = useState(false)
  const [stopping, setStopping] = useState(false)
  const [startErr, setStartErr] = useState<string | null>(null)
  const [releasing, setReleasing] = useState(false)
  const [releaseMsg, setReleaseMsg] = useState<{ ok: boolean; text: string } | null>(null)
  // 对齐预检：点"检查对齐"或者被 412 拒绝时填充这个 state
  const [alignment, setAlignment] = useState<AlignmentReport | null>(null)
  const [checkingAlignment, setCheckingAlignment] = useState(false)

  const running = session?.running === true

  // ---- WebSocket to /ws/ui for live joint updates ----
  const { state: wsState, lastUpdate, fps, connect, disconnect } =
    useTeleopWebSocket({ url: '/ws/ui', autoConnect: false, reconnect: true })

  // Auto-connect the viewer when session is running, disconnect when it stops.
  useEffect(() => {
    if (running && wsState !== 'connected' && wsState !== 'connecting') {
      connect()
    } else if (!running && (wsState === 'connected' || wsState === 'connecting')) {
      disconnect()
    }
    // We intentionally only react to `running` — connect/disconnect identities
    // change on every render but the ref-based hook makes that safe.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running])

  const joints: JointMap = useMemo(() => {
    if (!lastUpdate) return EMPTY_JOINTS
    return { ...EMPTY_JOINTS, ...lastUpdate.joints } as JointMap
  }, [lastUpdate])

  // ---- Motion detection: watch last N ms of joint deltas ----
  const motionHistoryRef = useRef<Array<{ t: number; sumAbsDelta: number }>>([])
  const prevJointsRef = useRef<JointMap>(EMPTY_JOINTS)
  const [motionDetected, setMotionDetected] = useState(false)

  useEffect(() => {
    if (!running || !lastUpdate) return
    const now = performance.now()
    let sum = 0
    for (const name of JOINT_NAMES) {
      const cur = Number(joints[name] ?? 0)
      const prev = Number(prevJointsRef.current[name] ?? 0)
      sum += Math.abs(cur - prev)
    }
    prevJointsRef.current = joints
    const history = motionHistoryRef.current
    history.push({ t: now, sumAbsDelta: sum })
    while (history.length && now - history[0].t > MOTION_WINDOW_MS) history.shift()
    const total = history.reduce((a, b) => a + b.sumAbsDelta, 0)
    setMotionDetected(total >= MOTION_THRESHOLD_RAD)
  }, [lastUpdate, joints, running])

  // Reset motion detection when teleop stops.
  useEffect(() => {
    if (!running) {
      motionHistoryRef.current = []
      prevJointsRef.current = EMPTY_JOINTS
      setMotionDetected(false)
    }
  }, [running])

  // ---- API helpers ----
  const refreshStatus = useCallback(async () => {
    try {
      const r = await agentFetch('/api/teleop/status')
      if (!r.ok) return
      const body = (await r.json()) as SessionStatus
      setSession(body)
    } catch {
      // transient — ignore
    }
  }, [])

  // Poll status while session is running so we catch crashed subprocesses.
  useEffect(() => {
    void refreshStatus()
    const id = setInterval(refreshStatus, 2000)
    return () => clearInterval(id)
  }, [refreshStatus])

  // force=true 跳过后端对齐预检 —— 仅在用户已经看到"偏差"面板后主动选的
  // "我已对齐、继续启动"兜底才走这条路。
  const startTeleop = useCallback(
    async (force: boolean) => {
      if (!leaderPort || !followerPort) return
      setStarting(true)
      setStartErr(null)
      if (!force) setAlignment(null)
      try {
        const r = await agentFetch('/api/teleop/start', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            leader_port: leaderPort,
            follower_port: followerPort,
            torque_on_start: true,
            force,
          }),
        })
        const body = await r.json().catch(() => ({} as Record<string, unknown>))
        if (!r.ok) {
          const detail = (body as { detail?: unknown }).detail
          // 后端 412 / code=arms_not_aligned 带 alignment 结构，专门展示
          if (
            typeof detail === 'object' &&
            detail &&
            (detail as { code?: string }).code === 'arms_not_aligned' &&
            'alignment' in detail
          ) {
            setAlignment((detail as { alignment: AlignmentReport }).alignment)
            setStartErr(null)
            return
          }
          const msg =
            typeof detail === 'string'
              ? detail
              : typeof detail === 'object' && detail && 'message' in detail
              ? String((detail as { message: unknown }).message)
              : `HTTP ${r.status}`
          setStartErr(msg)
          return
        }
        setAlignment(null)
        setSession(body as SessionStatus)
      } catch (e) {
        setStartErr((e as Error).message)
      } finally {
        setStarting(false)
      }
    },
    [leaderPort, followerPort],
  )

  const doStart = useCallback(() => startTeleop(false), [startTeleop])
  const doForceStart = useCallback(() => startTeleop(true), [startTeleop])

  const doCheckAlignment = useCallback(async () => {
    if (!leaderPort || !followerPort) return
    setCheckingAlignment(true)
    setStartErr(null)
    try {
      const r = await agentFetch('/api/teleop/alignment_check', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          leader_port: leaderPort,
          follower_port: followerPort,
        }),
      })
      const body = (await r.json()) as AlignmentReport & {
        detail?: string | { message?: string }
      }
      if (!r.ok) {
        const msg =
          typeof body?.detail === 'string'
            ? body.detail
            : typeof body?.detail === 'object' && body.detail?.message
            ? body.detail.message
            : `HTTP ${r.status}`
        setStartErr(String(msg))
        return
      }
      setAlignment(body)
    } catch (e) {
      setStartErr((e as Error).message)
    } finally {
      setCheckingAlignment(false)
    }
  }, [leaderPort, followerPort])

  const doStop = useCallback(async () => {
    setStopping(true)
    try {
      const r = await agentFetch('/api/teleop/stop', { method: 'POST' })
      if (r.ok) {
        const body = (await r.json()) as SessionStatus
        setSession(body)
      }
    } catch {
      // ignore — status poll will correct
    } finally {
      setStopping(false)
    }
  }, [])

  const doReleaseTorque = useCallback(async () => {
    if (!followerPort) return
    setReleasing(true)
    setReleaseMsg(null)
    try {
      const r = await agentFetch('/api/teleop/release_torque', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ port: followerPort }),
      })
      const body = await r.json().catch(() => ({} as Record<string, unknown>))
      if (!r.ok) {
        const detail = (body as { detail?: unknown }).detail
        const msg = typeof detail === 'string' ? detail : `HTTP ${r.status}`
        setReleaseMsg({ ok: false, text: msg })
        return
      }
      setReleaseMsg({
        ok: Boolean((body as { ok?: boolean }).ok),
        text: String((body as { message?: string }).message ?? ''),
      })
    } catch (e) {
      setReleaseMsg({ ok: false, text: (e as Error).message })
    } finally {
      setReleasing(false)
    }
  }, [followerPort])

  // Stop on unmount so the user doesn't accidentally leave motors torqued.
  useEffect(() => {
    return () => {
      void agentFetch('/api/teleop/stop', { method: 'POST' }).catch(() => null)
    }
  }, [])

  // ---- Derived UI bits ----
  const prereqMissing = !leaderPort || !followerPort
  const deadProcess = session?.processes?.find((p) => !p.alive && p.returncode != null)
  const nextDisabled = !state.completed.teleop && !motionDetected

  return (
    <SetupStepCard
      stepId="teleop"
      title="遥操作试运行"
      description="启动主控臂到执行臂的链路。手动晃主控臂，确认虚拟模型和真实执行臂都能跟着动。"
      nextDisabled={nextDisabled}
      nextLabel={
        state.completed.teleop
          ? '下一步：录制数据集'
          : motionDetected
          ? '看到跟动了，下一步'
          : '请先启动并晃动主控臂'
      }
      onNext={() => {
        if (!state.completed.teleop) markComplete('teleop', true)
        void agentFetch('/api/teleop/stop', { method: 'POST' }).catch(() => null)
        goNext()
      }}
    >
      {prereqMissing && (
        <div className="flex items-start gap-2 rounded-md border border-amber-500/30 bg-amber-500/5 p-3 text-sm text-amber-300">
          <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
          <div>
            <div>还没指派主控臂 / 执行臂端口。</div>
            <div className="text-xs text-amber-300/80 mt-0.5">
              请先回到“连接设备”，测试端口并指派两只机械臂。
            </div>
          </div>
        </div>
      )}

      {!prereqMissing && (
        <>
          {/* 端口概览 */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-sm">
            <div className="rounded-md border border-[hsl(var(--border))]/60 bg-[hsl(var(--card))]/40 p-3">
              <div className="text-[11px] uppercase tracking-wide text-[hsl(var(--muted-foreground))]">
                主控臂（你用手晃的）
              </div>
              <code className="font-mono text-sm">{leaderPort}</code>
            </div>
            <div className="rounded-md border border-[hsl(var(--border))]/60 bg-[hsl(var(--card))]/40 p-3">
              <div className="text-[11px] uppercase tracking-wide text-[hsl(var(--muted-foreground))]">
                执行臂（接 12V 电源）
              </div>
              <code className="font-mono text-sm">{followerPort}</code>
            </div>
          </div>

          {/* 启动 / 停止 */}
          <div className="flex flex-wrap items-center gap-3">
            {!running ? (
              <>
                <Button onClick={doStart} disabled={starting || stopping || checkingAlignment}>
                  {starting ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Play className="h-4 w-4" />
                  )}
                  开始遥操作
                </Button>
                <Button
                  variant="outline"
                  onClick={doCheckAlignment}
                  disabled={starting || stopping || checkingAlignment}
                >
                  {checkingAlignment ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <ScanLine className="h-4 w-4" />
                  )}
                  检查姿态对齐
                </Button>
              </>
            ) : (
              <Button variant="destructive" onClick={doStop} disabled={stopping}>
                {stopping ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Square className="h-4 w-4" />
                )}
                {stopping ? '正在关闭扭矩…' : '停止'}
              </Button>
            )}

            {running && (
              <div className="flex items-center gap-2 rounded-md border border-emerald-500/30 bg-emerald-500/5 px-3 py-1.5 text-xs text-emerald-300">
                <CircleDot className="h-3.5 w-3.5 animate-pulse" />
                运行中
                {wsState === 'connected' && (
                  <span className="text-emerald-400/80">· {fps} Hz</span>
                )}
              </div>
            )}

            {stopping && (
              <div className="text-xs text-[hsl(var(--muted-foreground))]">
                正在关闭执行臂扭矩（约 3-5 秒）…
              </div>
            )}

            {!running && session?.session_id && deadProcess && (
              <div className="text-xs text-red-300">
                上次会话 <code className="font-mono">{deadProcess.role}</code> 意外退出（returncode={deadProcess.returncode}），请查看下方日志。
              </div>
            )}
          </div>

          {startErr && (
            <div className="rounded-md border border-red-500/30 bg-red-500/5 p-3 text-sm text-red-300">
              启动失败：{startErr}
            </div>
          )}

          {/* 对齐预检结果 —— 被 412 拒绝或主动点"检查对齐"都会塞这里 */}
          {alignment && (
            <div
              className={cn(
                'rounded-md border p-3 text-sm space-y-2',
                alignment.ok
                  ? 'border-emerald-500/30 bg-emerald-500/5 text-emerald-200'
                  : 'border-amber-500/40 bg-amber-500/5 text-amber-100',
              )}
            >
              {alignment.skipped ? (
                <div>
                  无法读取当前机械臂姿态（串口可能被占用），跳过对齐检查。
                </div>
              ) : alignment.ok ? (
                <div className="flex items-center gap-2">
                  <Activity className="h-4 w-4" />
                  主臂和从臂姿态已对齐，可以直接开始。
                </div>
              ) : (
                <>
                  <div className="font-medium flex items-center gap-2">
                    <AlertTriangle className="h-4 w-4" />
                    主臂和从臂姿态不一致
                  </div>
                  <div className="text-xs text-amber-200/80">
                    直接启动的话，从臂会"一步跳"到主臂姿态，可能撞到桌面或外壳。
                    请用手把 <b>主臂</b> 按下面每一行指示稍微调整一下，让它靠近从臂的位置，
                    然后再点「开始遥操作」。
                  </div>
                  <ul className="space-y-1 text-xs">
                    {alignment.mismatches.map((m) => (
                      <li
                        key={m.motor}
                        className="flex items-start gap-2 rounded border border-amber-500/20 bg-amber-500/5 px-2 py-1"
                      >
                        <span className="font-mono text-amber-300 shrink-0 w-24">
                          {MOTOR_LABELS_ZH[m.motor] ?? m.motor}
                        </span>
                        <span className="font-mono text-amber-200/90 shrink-0 w-16 tabular-nums">
                          {m.delta_deg > 0 ? '+' : ''}
                          {m.delta_deg.toFixed(1)}°
                        </span>
                        <span className="text-amber-100/90">
                          主臂比从臂 {m.delta_deg > 0 ? '多' : '少'}{' '}
                          {Math.abs(m.delta_deg).toFixed(0)} 度，请把主臂这个关节反向移动一下
                        </span>
                      </li>
                    ))}
                  </ul>
                  <div className="flex flex-wrap items-center gap-2 pt-1">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={doCheckAlignment}
                      disabled={checkingAlignment}
                    >
                      {checkingAlignment ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <ScanLine className="h-3.5 w-3.5" />
                      )}
                      重新检查
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={doForceStart}
                      disabled={starting}
                      className="text-amber-200 hover:text-amber-100"
                    >
                      我已对齐、强制开始
                    </Button>
                    <span className="text-[11px] text-amber-300/70">
                      容差 ±{alignment.tolerance.toFixed(0)}%
                    </span>
                  </div>
                </>
              )}
            </div>
          )}

          {/* 救援：从臂卡死时一键松开扭矩 */}
          {!running && (
            <div className="rounded-md border border-[hsl(var(--border))]/40 bg-[hsl(var(--muted))]/20 px-3 py-2 space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={doReleaseTorque}
                  disabled={releasing || !followerPort}
                >
                  {releasing ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Unlock className="h-3.5 w-3.5" />
                  )}
                  松开从臂扭矩
                </Button>
                <span className="text-[11px] text-[hsl(var(--muted-foreground))]">
                  执行臂被锁住搬不动？点这个，可以用手自由摆到和主控臂接近的位置，再开始遥操作。
                </span>
              </div>
              {releaseMsg && (
                <div
                  className={cn(
                    'rounded px-2 py-1 text-xs',
                    releaseMsg.ok
                      ? 'border border-emerald-500/30 bg-emerald-500/5 text-emerald-300'
                      : 'border border-red-500/30 bg-red-500/5 text-red-300',
                  )}
                >
                  {releaseMsg.text}
                </div>
              )}
            </div>
          )}

          {/* 提示：动手晃主控臂 */}
          {running && !motionDetected && (
            <div className="flex items-start gap-2 rounded-md border border-[hsl(var(--primary))]/40 bg-[hsl(var(--primary))]/10 p-3 text-sm">
              <Hand className="h-4 w-4 mt-0.5 shrink-0 text-[hsl(var(--primary))]" />
              <div>
                <div className="font-medium">现在用手慢慢晃主控臂。</div>
                <div className="text-xs text-[hsl(var(--muted-foreground))] mt-0.5">
                  下方虚拟模型应该实时跟着变化，执行臂也会同步动作。
                  检测到明显动作后，「下一步」按钮会自动点亮。
                </div>
              </div>
            </div>
          )}
          {running && motionDetected && (
            <div className="flex items-start gap-2 rounded-md border border-emerald-500/40 bg-emerald-500/10 p-3 text-sm text-emerald-200">
              <Activity className="h-4 w-4 mt-0.5 shrink-0" />
              <div>
                检测到持续的关节变化，链路工作正常。如果你也看到执行臂跟着动了，就可以「下一步」。
              </div>
            </div>
          )}

          {/* URDF 预览 + 关节数值 */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
            <div className="lg:col-span-2 rounded-lg border border-[hsl(var(--border))]/60 overflow-hidden bg-black/30">
              <div className="h-[320px]">
                <UrdfViewer joints={joints} />
              </div>
            </div>
            <div className="rounded-lg border border-[hsl(var(--border))]/60 bg-[hsl(var(--card))]/40 p-3">
              <div className="text-[11px] uppercase tracking-wide text-[hsl(var(--muted-foreground))] mb-2">
                关节 (rad)
              </div>
              <div className="grid grid-cols-2 gap-2">
                {JOINT_NAMES.map((n) => {
                  const v = Number(joints[n] ?? 0)
                  return (
                    <div
                      key={n}
                      className="rounded-md border border-[hsl(var(--border))]/40 px-2 py-1.5"
                    >
                      <div className="text-[10px] text-[hsl(var(--muted-foreground))]">
                        J{n}
                      </div>
                      <div className="font-mono text-xs tabular-nums">
                        {v.toFixed(3)}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          </div>

          {/* 诊断日志（折叠，默认收起） */}
          {session?.processes && session.processes.length > 0 && (
            <details className="rounded-md border border-[hsl(var(--border))]/40 bg-[hsl(var(--muted))]/10 px-3 py-2 text-xs">
              <summary className="cursor-pointer select-none text-[hsl(var(--foreground))]">
                诊断日志（出问题时展开）
              </summary>
              <div className="mt-2 space-y-2">
                {session.processes.map((p) => (
                  <div key={p.role}>
                    <div
                      className={cn(
                        'text-[11px] font-medium',
                        p.alive ? 'text-emerald-400' : 'text-red-300',
                      )}
                    >
                      {p.role} · pid={p.pid} · {p.alive ? 'alive' : `exited(${p.returncode ?? '?'})`}
                    </div>
                    <pre className="mt-1 whitespace-pre-wrap break-all font-mono text-[10.5px] leading-4 text-[hsl(var(--muted-foreground))] max-h-40 overflow-auto">
                      {p.stderr_tail.slice(-15).join('\n') || '(no output yet)'}
                    </pre>
                  </div>
                ))}
              </div>
            </details>
          )}
        </>
      )}
    </SetupStepCard>
  )
}
