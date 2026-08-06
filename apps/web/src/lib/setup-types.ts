/**
 * M9.2 — Setup Wizard types & shared constants.
 *
 * The wizard is runtime-scoped: the state object is namespaced by runtime_id
 * so when we later add more runtimes (reachy_mini, etc.) they won't stomp
 * each other's progress in localStorage.
 *
 * Visible SO-101 path:
 *   0  connect        Pick camera + identify leader/follower arms
 *   1  teleop         Required safety dry run before recording
 *   2  record         Record a short dataset
 *   3  run            Train a model, then launch inference
 */

export type SetupStepId =
  | 'connect'
  | 'camera'
  | 'arm'
  | 'teleop'
  | 'record'
  | 'train'
  | 'inference'
  | 'run'

export interface SetupStepMeta {
  id: SetupStepId
  index: number
  label: string
  shortHint: string
  /** 这一步要完成什么 */
  goal: string
  /** 用户看到什么算成功 */
  successSignal: string
  /** 卡住时可以问 Copilot 的话 */
  copilotHint: string
}

export const SO101_STEPS: SetupStepMeta[] = [
  {
    id: 'connect',
    index: 0,
    label: '连接设备',
    shortHint: '选相机，识别主控臂和执行臂',
    goal: '让网站能识别你的摄像头和两只机械臂',
    successSignal: '相机预览有画面，主控臂和执行臂各选一个串口',
    copilotHint: '摄像头检测不到 / 串口没有权限',
  },
  {
    id: 'teleop',
    index: 1,
    label: '遥操作试运行',
    shortHint: '先确认执行臂能跟着主控臂动',
    goal: '确认主控臂动作能安全传递到执行臂',
    successSignal: '手动晃主控臂时，执行臂明显跟动',
    copilotHint: '遥操作没反应 / 执行臂不动',
  },
  {
    id: 'record',
    index: 2,
    label: '录一段示教',
    shortHint: '采集一组可训练的数据',
    goal: '录下至少一段可用来训练的示教数据',
    successSignal: '录制结束并生成数据集，可在列表中看到',
    copilotHint: '录制失败 / 数据集保存不了',
  },
  {
    id: 'run',
    index: 3,
    label: '训练并运行',
    shortHint: '训练模型，然后启动推理',
    goal: '用刚录的数据训练模型，并跑通一次推理',
    successSignal: '训练任务完成，推理页能加载模型并出结果',
    copilotHint: '训练任务失败了怎么办 / 需要登录吗',
  },
]

export const B601_STEPS: SetupStepMeta[] = [
  {
    id: 'connect',
    index: 0,
    label: '连接设备',
    shortHint: '从臂、主臂、相机、电源',
    goal: '确认机械臂和主臂都已连接并上电',
    successSignal: '底部 CAN / 主臂 / 从臂 为绿色；标定在下拉框选 ID',
    copilotHint: '从臂没力气 / 主臂检测不到 / CAN 未连接',
  },
  {
    id: 'teleop',
    index: 1,
    label: '试遥操',
    shortHint: '动主臂，从臂会跟着动',
    goal: '确认主从遥操正常工作',
    successSignal: '遥操运行中，从臂跟随主臂动作',
    copilotHint: '遥操启动失败 / 从臂软掉',
  },
  {
    id: 'record',
    index: 2,
    label: '录示教',
    shortHint: '采集第一条训练数据',
    goal: '录制至少一段示教数据',
    successSignal: '录制完成，数据集已保存',
    copilotHint: '录制失败 / episode 进度卡住',
  },
  {
    id: 'run',
    index: 3,
    label: '训练并运行',
    shortHint: '云端训练并部署',
    goal: '用刚录的数据训练模型并部署到机械臂',
    successSignal: '训练完成，策略可在机械臂上运行',
    copilotHint: '云端训练失败 / 部署没反应',
  },
]

export function stepsForRuntime(runtimeId: string): SetupStepMeta[] {
  if (runtimeId === 'b601_rs') return B601_STEPS
  return SO101_STEPS
}

export interface CameraChoice {
  deviceIndex: number // /dev/videoN  -> N
  label: string // "Camera 0 (640x480@30)"
  width: number
  height: number
  fps: number
}

export interface PortChoice {
  port: string // "/dev/ttyACM0"
  motorCount: number
  looksLikeFeetech: boolean
}

export interface SetupState {
  runtimeId: string // "so101" for now
  currentStep: SetupStepId
  // Per-step completion flags. A step is "complete" when the user has
  // produced the required artefact (selected a camera, picked a port, etc.).
  completed: Record<SetupStepId, boolean>
  // Artefacts the later steps consume:
  camera: CameraChoice | null
  // SO-101 has two arms: a "leader" (user grabs it to demonstrate motions,
  // no 12V motor power needed) and a "follower" (driven by 12V, replays /
  // executes the leader). Teleop/record both require BOTH ports; earlier
  // versions of the wizard only tracked follower which meant Step 3 had
  // nothing to wire up.
  followerPort: PortChoice | null
  leaderPort: PortChoice | null
  lastDatasetId: string | null // set after a record
  lastModelKey: string | null // set after a training finishes
}

export function makeInitialSetupState(runtimeId: string): SetupState {
  const isB601 = runtimeId === 'b601_rs'
  return {
    runtimeId,
    currentStep: isB601 ? 'connect' : 'camera',
    completed: {
      connect: false,
      camera: false,
      arm: false,
      teleop: false,
      record: false,
      train: false,
      inference: false,
      run: false,
    },
    camera: null,
    followerPort: null,
    leaderPort: null,
    lastDatasetId: null,
    lastModelKey: null,
  }
}

export function storageKey(runtimeId: string): string {
  return `botversex.setup.${runtimeId}.v1`
}

function visibleStepId(step: SetupStepId): SetupStepId {
  if (step === 'camera' || step === 'arm') return 'connect'
  if (step === 'train' || step === 'inference') return 'run'
  return step
}

/** Whether the wizard allows jumping to step `target` given current progress. */
export function canJumpTo(state: SetupState, target: SetupStepId): boolean {
  // B601: all steps stay navigable — hardware may already be connected; don't lock users out.
  if (state.runtimeId === 'b601_rs') return true

  const steps = stepsForRuntime(state.runtimeId)
  const visibleTarget = visibleStepId(target)
  const targetIdx = steps.findIndex((s) => s.id === visibleTarget)
  if (targetIdx <= 0) return true
  if (visibleTarget === 'teleop') return state.completed.connect
  if (visibleTarget === 'record') return state.completed.connect && state.completed.teleop
  if (visibleTarget === 'run') {
    return state.completed.connect && state.completed.teleop && state.completed.record
  }
  return false
}

/** The first step that is NOT complete — used as "Resume" default. */
export function firstIncomplete(state: SetupState): SetupStepId {
  const steps = stepsForRuntime(state.runtimeId)
  for (const s of steps) {
    if (!state.completed[s.id]) return s.id
  }
  return 'run'
}

// ---- Shared API response shapes (kept here to avoid dup types) -----------

export interface SetupHealth {
  realtime_ok: boolean
  platform: string
  python_version: string
  lerobot_available: boolean
  pytorch_available: boolean
  opencv_available: boolean
  video_device_count: number
  serial_device_count: number
  dialout_member: boolean | null
  rocm_probe_ok: boolean | null
  rocm_probe_message: string | null
}

export interface SetupIssue {
  severity: 'error' | 'warning' | 'info'
  code: string
  message: string
}

export interface SetupStatus {
  overall: 'ok' | 'warning' | 'error'
  checks: {
    api: { ok: boolean }
    database: { ok: boolean; error: string | null }
    realtime: { reachable: boolean; url: string; error: string | null }
    runtime: SetupHealth | null
  }
  issues: SetupIssue[]
  next_action: { label: string; path: string }
}

export interface PortsResponse {
  ports: Array<{
    port: string
    description: string
    motor_count: number
    motor_ids: number[]
    looks_like_feetech: boolean
    error: string | null
  }>
  scanned_count: number
  platform: string
}

export interface CameraDeviceInfo {
  index: number
  path: string
  width: number
  height: number
  fps: number
  backend: string
}

export interface WiggleResponse {
  ok: boolean
  available: boolean
  message: string
  port: string
  // Informational only — we never use voltage to decide Leader vs Follower
  // (both arms can physically wiggle). Rendered as a small hint next to the
  // port so users see "11.9V" or "7.6V" and can sanity-check their setup.
  present_voltage_v: number | null
}
