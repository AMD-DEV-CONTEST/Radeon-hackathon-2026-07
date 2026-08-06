import { Suspense } from 'react'
import { CheckCircle2, Circle, Loader2, Plug, Usb, Zap } from 'lucide-react'
import { UrdfViewer } from '../features/UrdfViewer'
import { StatusLight } from '../shared/StatusLight'
import {
  isB601BrowseOnly,
  isB601CanWaitingMotors,
  isB601HardwareReady,
  type B601Health,
} from '../../lib/b601Api'
import { B601_ARM_JOINTS, b601JointsToUrdf } from '../../lib/b601Joints'
import { B601_URDF_STAGE } from '../../lib/b601Urdf'
import { cn } from '../../lib/utils'

export type B601StageFocus = 'idle' | 'teleop' | 'record' | 'playback'

interface Props {
  health: B601Health | null
  cameraPreviewUrl?: string | null
  pipBroken?: boolean
  onPipError?: () => void
  onPipLoad?: () => void
  recovering?: boolean
  teleopRunning?: boolean
  gravityCompRunning?: boolean
  /** Current focus — drives which overlays matter. */
  focus?: B601StageFocus
  playJoints?: Record<string, number> | null
  /** Motor-space joint1..joint7 for the HUD (degrees shown). */
  jointHud?: Record<string, number> | null
  onMeshFailed?: (url: string) => void
  /** Shorter stage while recording (right panel is primary). */
  compact?: boolean
  /** Optional record coach summary on the stage (episode / phase). */
  recordCoachLine?: string | null
}

const FOCUS_LABEL: Record<B601StageFocus, string> = {
  idle: '试玩 / 连接',
  teleop: '遥操 · 3D 实时跟从臂',
  record: '采集中 · 看右侧阶段与计时',
  playback: '回放',
}

export function B601Stage({
  health,
  cameraPreviewUrl,
  pipBroken,
  onPipError,
  onPipLoad,
  recovering,
  teleopRunning = false,
  gravityCompRunning = false,
  focus = 'idle',
  playJoints = null,
  jointHud = null,
  onMeshFailed,
  compact = false,
  recordCoachLine = null,
}: Props) {
  const followerOk = (health?.motors_online ?? 0) >= 5
  const leaderOk = health?.leader_present ?? false
  const canOk = health?.can_up ?? false
  const calOk = health?.calibration_follower && health?.calibration_leader
  const browseOnly = isB601BrowseOnly(health)
  const waitingMotors = isB601CanWaitingMotors(health)
  const hardwareReady = isB601HardwareReady(health)
  const needsCalibration = hardwareReady && !calOk

  const displayJoints = playJoints?.gripper_joint1 !== undefined
    ? playJoints
    : b601JointsToUrdf(playJoints)

  const showJointHud =
    (focus === 'teleop' || focus === 'playback') &&
    jointHud &&
    Object.keys(jointHud).length >= 3

  return (
    <div
      className={cn(
        'relative overflow-hidden rounded-xl border border-white/5 bg-gradient-to-b from-[#0d1220] to-[#070a12]',
        compact ? 'min-h-[280px] h-[280px]' : 'min-h-[480px] h-full',
      )}
    >
      <div className="absolute inset-0 bottom-10">
        <Suspense
          fallback={
            <div className="flex h-full items-center justify-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="h-5 w-5 animate-spin text-primary" />
              加载 3D 模型…
            </div>
          }
        >
          <UrdfViewer
            urdfUrl={B601_URDF_STAGE}
            className="h-full w-full"
            joints={displayJoints}
            jointSmoothing={teleopRunning || gravityCompRunning ? 72 : focus === 'playback' ? 140 : 22}
            waitForMeshes
            hideMeshProgress={false}
            meshConcurrency={1}
            cameraPosition={[0.55, 0.42, 0.55]}
            orbitTarget={[0, 0.12, 0]}
            onMeshFailed={onMeshFailed}
          />
        </Suspense>
      </div>

      <div className="absolute left-3 top-3 z-10 rounded-md border border-white/10 bg-black/70 px-2 py-1 text-[10px] text-muted-foreground">
        虚拟从臂 · <span className="text-foreground/90">{FOCUS_LABEL[focus]}</span>
      </div>

      {showJointHud && (
        <div className="absolute right-3 top-3 z-10 max-w-[200px] rounded-lg border border-white/10 bg-black/75 px-2.5 py-2 text-[10px] shadow-lg backdrop-blur-sm">
          <div className="mb-1 font-medium text-foreground/90">
            {focus === 'teleop' ? '实时关节' : '回放关节'}
          </div>
          <div className="grid grid-cols-1 gap-0.5 font-mono tabular-nums text-muted-foreground">
            {B601_ARM_JOINTS.map((j) => {
              const rad = jointHud[j.id]
              if (typeof rad !== 'number' || !Number.isFinite(rad)) return null
              const deg = (rad * 180) / Math.PI
              return (
                <div key={j.id} className="flex justify-between gap-3">
                  <span>{j.label}</span>
                  <span className="text-foreground/85">
                    {j.id === 'joint7' ? rad.toFixed(3) : `${deg.toFixed(0)}°`}
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {cameraPreviewUrl && !pipBroken && focus !== 'record' && (
        <div className="absolute bottom-14 right-3 z-10 w-36 overflow-hidden rounded-lg border border-white/10 shadow-lg">
          <img
            src={cameraPreviewUrl}
            alt="相机预览"
            className="h-auto w-full object-cover"
            onError={onPipError}
            onLoad={onPipLoad}
          />
        </div>
      )}

      {focus === 'record' && (
        <div className="absolute inset-x-0 top-10 z-10 mx-auto w-fit max-w-[min(92%,520px)] rounded-lg border border-sky-500/40 bg-sky-950/90 px-4 py-2.5 text-center shadow-lg">
          <p className="text-sm font-semibold text-sky-50">
            {recordCoachLine || '采集进行中'}
          </p>
          <p className="mt-0.5 text-[11px] text-sky-100/85">
            重点看右侧教练板（条数 · 倒计时 · 复位/保存）
          </p>
        </div>
      )}

      {hardwareReady && !recovering && !teleopRunning && focus === 'idle' && (
        <div className="absolute inset-x-0 top-10 z-10 mx-auto w-fit max-w-[min(92%,520px)] rounded-lg border border-emerald-500/30 bg-emerald-950/75 px-3 py-2 text-center text-xs text-emerald-100">
          <span className="font-medium text-emerald-200">已连接真机</span>
          {' — '}
          从臂 {health?.motors_online}/{health?.motors_total ?? 7} 在线，可检查对齐并开始遥操。
        </div>
      )}

      {needsCalibration && !recovering && focus === 'idle' && (
        <div className="absolute inset-x-0 top-10 z-10 mx-auto w-fit max-w-[min(92%,520px)] rounded-lg border border-amber-500/30 bg-amber-950/75 px-3 py-2 text-center text-xs leading-relaxed text-amber-100">
          <span className="font-medium text-amber-200">硬件已连接 · 待标定</span>
          {' — '}
          请在「标定」面板完成主臂/从臂标定后再遥操。
        </div>
      )}

      {waitingMotors && !recovering && !hardwareReady && focus === 'idle' && (
        <div className="absolute inset-x-0 top-10 z-10 mx-auto w-fit max-w-[min(92%,520px)] rounded-lg border border-amber-500/30 bg-amber-950/75 px-3 py-2 text-center text-xs leading-relaxed text-amber-100">
          <span className="font-medium text-amber-200">{health?.arm_variant === 'dm' ? 'DM 串口已通' : 'CAN 已通'}</span>
          {' — '}
          从臂 {health?.motors_online ?? 0}/{health?.motors_total ?? 7} 在线。
          请点下方重新扫描从臂或稍等扫描完成（勿连续多点）。
        </div>
      )}

      {browseOnly && !recovering && focus === 'idle' && (
        <div className="absolute inset-x-0 top-10 z-10 mx-auto w-fit max-w-[min(92%,520px)] rounded-lg border border-sky-500/30 bg-sky-950/75 px-3 py-2 text-center text-xs leading-relaxed text-sky-100">
          <span className="font-medium text-sky-200">试玩模式</span>
          {' — '}
          下方拖滑条只看 3D；接好从臂与主臂后在连接面板扫描即可连真机。
        </div>
      )}

      {recovering && (
        <div className="absolute inset-x-0 top-10 z-10 mx-auto w-fit max-w-[90%] rounded-full bg-amber-500/20 px-3 py-1 text-center text-xs text-amber-200">
          正在唤醒从臂（短促电机声属正常，约 10–20 秒）…
        </div>
      )}

      <div className="absolute inset-x-0 bottom-0 z-10 flex flex-wrap items-center gap-2 border-t border-white/5 bg-black/40 px-3 py-2 text-xs">
        <StatusLight label="从臂" ok={followerOk} okIcon={<Zap className="h-3 w-3" />} badIcon={<Circle className="h-3 w-3" />} />
        <StatusLight label="主臂" ok={leaderOk} okIcon={<Usb className="h-3 w-3" />} badIcon={<Circle className="h-3 w-3" />} />
        <StatusLight label={health?.arm_variant === 'dm' ? 'DM 串口' : 'CAN'} ok={canOk} okIcon={<Plug className="h-3 w-3" />} badIcon={<Circle className="h-3 w-3" />} />
        <StatusLight label="校准" ok={!!calOk} okIcon={<CheckCircle2 className="h-3 w-3" />} badIcon={<Circle className="h-3 w-3" />} />
        {canOk && (
          <span className="ml-auto text-[10px] text-emerald-400/90">
            从臂 {health?.motors_online ?? 0}/{health?.motors_total ?? 7} 在线
          </span>
        )}
      </div>
    </div>
  )
}
