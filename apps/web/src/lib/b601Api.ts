import { agentFetch } from './localAgent'

function friendlyB601Error(raw: string): string {
  try {
    const j = JSON.parse(raw) as { detail?: string | { message?: string; code?: string } }
    const d = j.detail
    if (d && typeof d === 'object' && d.code === 'b601_arms_not_aligned') {
      return d.message ?? '主从臂未对齐'
    }
    const text = typeof d === 'string' ? d : d?.message ?? raw
    if (text.includes('Port ') && text.includes(' is currently in use by')) {
      if (text.includes('b601-record') || text.includes('record')) {
        return (
          '主臂/从臂串口仍被上次采集占用（录制已结束但未释放）。' +
          '请点「停止采集」，或等 2 秒后重试；若仍失败请刷新页面。'
        )
      }
      return (
        '主臂/从臂串口仍被上次遥操或采集占用（进程已退出但未释放）。' +
        '请点「停止采集」或「停止遥操」，或等几秒后重试；若仍失败请刷新页面。'
      )
    }
    if (text.includes('从臂正忙') || text.includes('另一个操作进行中')) {
      return text
    }
    if (text.includes('lerobot-teleoperate not found') || text.includes('Is the realtime venv set up')) {
      return '官方遥操环境未安装。请运行：bash scripts/install-botversex-agent.sh'
    }
    if (text.includes('No such file or directory') && text.includes('lerobot')) {
      return '遥操环境路径无效。请运行：bash scripts/install-botversex-agent.sh'
    }
    if (/disable_all failed|control ack timeout/i.test(text)) {
      return '从臂 CAN 通信超时 — 请先点「停止遥操」，等 5 秒后重试；若仍失败，在连接面板点「唤醒从臂」再启动。'
    }
    if (text.includes('B601 API 502') || text.includes('502')) {
      return '代理超时 — 遥操可能仍在后台启动，请等 30–60 秒看状态是否变为「运行中」。'
    }
    if (/signal timed out|timeout/i.test(text)) {
      return 'CAN/电机通信超时。请等当前操作结束，勿连续多点；若臂异常请拔 48V 或按急停。'
    }
    if (text.includes('标定文件不存在')) {
      return text
    }
    if (/FileExistsError|File exists|数据集目录已存在/i.test(text)) {
      return (
        '这个数据集 ID 在磁盘上已经存在（上次失败或采过会留下文件夹）。' +
        '请点「换一个」用新 ID 再开始；系统也会尽量自动换新 ID。'
      )
    }
    return text.length > 200 ? `${text.slice(0, 200)}…` : text
  } catch {
    return raw.length > 200 ? `${raw.slice(0, 200)}…` : raw
  }
}

export interface B601MotorScanItem {
  motor_id: number
  model: string
  online: boolean
  faulted?: boolean
  label?: string
}

export interface B601Health {
  ok: boolean
  ready_for_teleop?: boolean
  arm_variant?: 'rs' | 'dm'
  follower_type?: string
  follower_transport?: string
  follower_port?: string
  can_up: boolean
  can_present?: boolean
  can_iface: string
  leader_present: boolean
  leader_port: string
  motors_online: number
  motors_total: number
  motors?: B601MotorScanItem[]
  motors_scan_stale?: boolean
  calibration_follower: boolean
  calibration_leader: boolean
  motorbridge_cli: boolean
  lerobot_teleoperate: boolean
  gateway_running: boolean
  cameras_available: number
  power_hint: string | null
  issues: string[]
  robot_id?: string
  leader_id?: string
}

export interface B601Config {
  arm_variant: 'rs' | 'dm'
  follower_port: string
  follower_type: string
  follower_transport: string
  robot_id: string
  leader_id: string
  follower_ids: string[]
  leader_ids: string[]
  calibration_follower: boolean
  calibration_leader: boolean
}

/** CAN + 主臂 + 从臂电机已检测到（不要求已完成标定）。 */
export function isB601HardwareReady(health: B601Health | null | undefined): boolean {
  return !!health?.ok
}

/** 仅无 CAN 且无主臂时才算「纯试玩」（避免 CAN 绿灯仍显示试玩模式）。 */
export function isB601BrowseOnly(health: B601Health | null | undefined): boolean {
  if (!health) return true
  return !health.can_up && !health.leader_present
}

/** CAN 已通但电机未齐 — 常见于扫描中或总线忙。 */
export function isB601CanWaitingMotors(health: B601Health | null | undefined): boolean {
  if (!health?.can_up) return false
  return (health.motors_online ?? 0) < 5
}

export function b601StatusLine(health: B601Health | null | undefined): string {
  if (!health) return '正在连接 Local Agent…'
  const linkName = health.arm_variant === 'dm' ? 'DM 串口' : 'CAN'
  const armName = health.arm_variant === 'dm' ? 'B601-DM' : 'B601-RS'
  if (health.ok) return `${armName} 已连接 · 从臂 ${health.motors_online}/${health.motors_total ?? 7} 在线`
  if (health.can_up && (health.motors_online ?? 0) < 5) {
    return `${linkName} 已通 · 从臂 ${health.motors_online}/${health.motors_total ?? 7} 在线（若长期为 0 请点「重新扫描从臂」）`
  }
  if (health.can_present && !health.can_up) {
    return health.arm_variant === 'dm' ? 'DM 串口已识别 · 等待扫描' : 'PCAN 已插入 · 请在下方面板输入密码连接'
  }
  if (health.leader_present && !health.can_up) return '主臂已识别 · 等待 CAN'
  return '未检测到硬件 · 可拖滑条试玩 3D'
}

/** 官方 lerobot-teleoperate 就绪：硬件 + 主从臂标定文件。 */
export function isB601ReadyForTeleop(health: B601Health | null | undefined): boolean {
  if (!health) return false
  return health.ready_for_teleop === true || (
    health.ok && health.calibration_follower && health.calibration_leader
  )
}

export interface B601Session {
  running: boolean
  starting?: boolean
  healthy?: boolean
  last_error?: string | null
  role: string
  session_id?: string | null
  pid?: number | null
  started_at?: number | null
  uptime_s?: number | null
  log_tail: string[]
  episode_current?: number | null
  episode_total?: number | null
  calibrate_target?: string | null
  robot_id?: string | null
  leader_id?: string | null
  follower_cal_path?: string | null
  leader_cal_path?: string | null
  returncode?: number | null
  repo_id?: string | null
  dataset_dir?: string | null
  record_phase?: string | null
  phase_hint?: string | null
  episode_time_s?: number | null
  reset_time_s?: number | null
  phase_elapsed_s?: number | null
}

export interface B601DatasetPushResult {
  ok: boolean
  local_repo_id: string
  hub_repo_id?: string | null
  url?: string | null
  message: string
  bytes_uploaded_hint?: string | null
}

export interface B601TeleopPreflight {
  ok: boolean
  robot_id: string
  leader_id: string
  follower_cal_path?: string | null
  leader_cal_path?: string | null
  calibration_follower: boolean
  calibration_leader: boolean
  follower_joints: Record<string, number>
  warnings: string[]
}

export interface B601AlignMismatch {
  motor: string
  label: string
  delta_deg: number
  leader_deg: number
  follower_deg: number
  hint: string
}

export interface B601Alignment {
  ok: boolean
  tolerance_deg: number
  skipped: boolean
  skip_reason?: string | null
  mismatches: B601AlignMismatch[]
  robot_id: string
  leader_id: string
}

export class B601ArmsNotAlignedError extends Error {
  readonly alignment: B601Alignment

  constructor(message: string, alignment: B601Alignment) {
    super(message)
    this.name = 'B601ArmsNotAlignedError'
    this.alignment = alignment
  }
}

async function b601Json<T>(path: string, init?: RequestInit & { timeoutMs?: number }): Promise<T> {
  const timeoutMs =
    init?.timeoutMs ??
    (['POST', 'PUT', 'PATCH', 'DELETE'].includes((init?.method ?? 'GET').toUpperCase()) ? 120_000 : 30_000)
  const { timeoutMs: _t, ...rest } = init ?? {}
  let res: Response
  try {
    res = await agentFetch(path, {
      ...rest,
      timeoutMs,
      headers: { 'Content-Type': 'application/json', ...rest.headers },
    })
  } catch (e) {
    if (e instanceof DOMException && (e.name === 'TimeoutError' || e.message.includes('timed out'))) {
      throw new Error('操作超时 — 请等当前步骤完成后再试，勿连续多点。若遥操启动中，可等 30–60 秒。')
    }
    throw e
  }
  const text = await res.text().catch(() => '')
  if (!res.ok) {
    try {
      const j = JSON.parse(text) as {
        detail?: { code?: string; message?: string; alignment?: B601Alignment }
      }
      const detail = j.detail
      if (res.status === 412 && detail?.alignment) {
        if (detail.code === 'b601_arms_not_aligned' || detail.code === 'b601_alignment_skipped') {
          throw new B601ArmsNotAlignedError(detail.message ?? '主从臂未对齐', detail.alignment)
        }
      }
    } catch (e) {
      if (e instanceof B601ArmsNotAlignedError) throw e
    }
    throw new Error(friendlyB601Error(text || `B601 API ${res.status}`))
  }
  return (text ? JSON.parse(text) : {}) as T
}

export function getB601Config() {
  return b601Json<B601Config>('/api/b601/config')
}

export function setB601Config(opts: { arm_variant?: 'rs' | 'dm'; follower_port?: string; robot_id?: string; leader_id?: string }) {
  return b601Json<B601Config>('/api/b601/config', {
    method: 'POST',
    body: JSON.stringify(opts),
  })
}

export function deleteB601Calibration(side: 'follower' | 'leader', calId: string) {
  return b601Json<B601Config>('/api/b601/calibration/file', {
    method: 'DELETE',
    body: JSON.stringify({ side, cal_id: calId }),
  })
}

export function getB601Health() {
  return b601Json<B601Health>('/api/b601/health')
}

/**
 * Read health; if PCAN is plugged but CAN down, auto-run probe once (sudo + scan).
 * Use on page open so users don't stare at a static「浏览模式」.
 */
export async function refreshB601Health(opts?: {
  forceProbe?: boolean
  wakeFollower?: boolean
  /** 遥操/对齐/读取关节进行中 — 勿自动 probe 抢 CAN */
  skipAutoProbe?: boolean
}) {
  if (opts?.forceProbe || opts?.wakeFollower) {
    return b601Probe({ wakeFollower: opts.wakeFollower ?? false })
  }
  const h = await getB601Health()
  if (opts?.skipAutoProbe) return h
  if (h.arm_variant === 'dm' && h.can_present && (h.motors_online ?? 0) < 5) {
    return b601Probe({ wakeFollower: true })
  }
  if (h.can_present && !h.can_up) {
    return b601Probe({ wakeFollower: false })
  }
  if (h.can_up && (h.motors_online ?? 0) < 5) {
    return b601Probe({ wakeFollower: true })
  }
  return h
}

/** 官方首连：sudo 拉起 CAN + 可选唤醒从臂 + 重新扫描（对应 rebot-setup-can + scan）。 */
export function b601Probe(opts?: { wakeFollower?: boolean; sudoPassword?: string }) {
  return b601Json<B601Health>('/api/b601/probe', {
    method: 'POST',
    body: JSON.stringify({
      wake_follower: opts?.wakeFollower ?? false,
      sudo_password: opts?.sudoPassword || undefined,
    }),
  })
}

export function b601CanUp(opts?: { sudoPassword?: string }) {
  return b601Json<{ ok: boolean; message: string }>('/api/b601/can/up', {
    method: 'POST',
    body: JSON.stringify({ sudo_password: opts?.sudoPassword || undefined }),
  })
}

export function b601Recover() {
  return b601Json<{ ok: boolean; message: string }>('/api/b601/recover', { method: 'POST' })
}

/** 逐 ID ping 1..7（只读，不写寄存器/不改 ID）。 */
export function b601MotorsDiagnose() {
  return b601Json<{
    ok: boolean
    motors: B601MotorScanItem[]
    motors_online: number
    motors_total: number
    message: string
    issues: string[]
    read_only: boolean
  }>('/api/b601/motors/diagnose')
}

export function b601MotorScan() {
  return b601Json<B601MotorScanItem[]>('/api/b601/scan')
}

export function b601Disable() {
  return b601Json<{ ok: boolean; message: string }>('/api/b601/disable', { method: 'POST' })
}

export function b601TeleopStart(opts?: {
  displayData?: boolean
  useCameras?: boolean
  cameraIndices?: number[]
  restart?: boolean
  robotId?: string
  leaderId?: string
  force?: boolean
  armVariant?: 'rs' | 'dm'
  followerPort?: string
  fps?: number
}) {
  return b601Json<B601Session>('/api/b601/teleop/start', {
    method: 'POST',
    body: JSON.stringify({
      display_data: opts?.displayData ?? false,
      use_cameras: opts?.useCameras ?? false,
      camera_indices: opts?.cameraIndices ?? [0, 4],
      restart: opts?.restart ?? true,
      force: opts?.force ?? false,
      robot_id: opts?.robotId,
      leader_id: opts?.leaderId,
      arm_variant: opts?.armVariant,
      follower_port: opts?.followerPort,
      fps: opts?.fps,
    }),
  })
}

export function b601TeleopAlignment(opts?: { robotId?: string; leaderId?: string }) {
  const q = new URLSearchParams()
  if (opts?.robotId) q.set('robot_id', opts.robotId)
  if (opts?.leaderId) q.set('leader_id', opts.leaderId)
  const suffix = q.toString() ? `?${q}` : ''
  return b601Json<B601Alignment>(`/api/b601/teleop/alignment${suffix}`, { timeoutMs: 60_000 })
}

/** Fetch active calibration ids + warnings before teleop. */
export function b601TeleopPreflight(opts?: { robotId?: string; leaderId?: string }) {
  const q = new URLSearchParams()
  if (opts?.robotId) q.set('robot_id', opts.robotId)
  if (opts?.leaderId) q.set('leader_id', opts.leaderId)
  const suffix = q.toString() ? `?${q}` : ''
  return b601Json<B601TeleopPreflight>(`/api/b601/teleop/preflight${suffix}`)
}

/**
 * Safety gate: confirm calibration ids with user, then start teleop with explicit ids.
 * Returns null if user cancels.
 */
export async function b601TeleopStartWithConfirm(opts?: {
  useCameras?: boolean
  cameraIndices?: number[]
  skipConfirm?: boolean
  force?: boolean
}): Promise<B601Session | null> {
  const cfg = await getB601Config()
  if (!cfg.calibration_follower || !cfg.calibration_leader) {
    throw new Error(`标定未就绪 — 从臂 ${cfg.robot_id} / 主臂 ${cfg.leader_id} 标定文件缺失`)
  }
  if (!opts?.skipConfirm && !opts?.force) {
    const ok = window.confirm(
      `即将启动遥操（官方 lerobot-teleoperate）\n\n` +
        `机型：${cfg.arm_variant === 'dm' ? 'B601-DM / 达妙串口' : 'B601-RS / PCAN'}\n` +
        `从臂连接：${cfg.follower_port}\n` +
        `从臂标定：${cfg.robot_id}\n` +
        `主臂标定：${cfg.leader_id}\n\n` +
        `请确认周围无人，启动后先缓慢试主臂。\n\n继续？`,
    )
    if (!ok) return null
  }
  return b601TeleopStart({
    restart: true,
    useCameras: opts?.useCameras ?? false,
    cameraIndices: opts?.cameraIndices,
    robotId: cfg.robot_id,
    leaderId: cfg.leader_id,
    armVariant: cfg.arm_variant,
    followerPort: cfg.follower_port,
    force: opts?.force ?? false,
  })
}

/** Emergency stop: disable motors immediately, then stop teleop process. */
export async function b601TeleopStopSafe() {
  void b601Disable().catch(() => {})
  return b601Json<B601Session>('/api/b601/teleop/stop', { method: 'POST' })
}

export function b601TeleopStop() {
  return b601Json<B601Session>('/api/b601/teleop/stop', { method: 'POST' })
}

export function b601TeleopStatus() {
  return b601Json<B601Session>('/api/b601/teleop/status')
}

/** Poll until teleop loop is running, failed, or timeout. */
export async function waitForB601TeleopReady(opts?: {
  timeoutMs?: number
  onTick?: (s: B601Session) => void
}): Promise<B601Session> {
  const deadline = Date.now() + (opts?.timeoutMs ?? 120_000)
  while (Date.now() < deadline) {
    const s = await b601TeleopStatus()
    opts?.onTick?.(s)
    if (s.running && s.healthy !== false) return s
    if (!s.starting && !s.running && s.last_error) throw new Error(s.last_error)
    await new Promise((r) => setTimeout(r, 2000))
  }
  throw new Error('遥操未在预期时间内就绪 — 请再点一次「开始遥操」')
}

/** 一键遥操：自动停止旧进程 → 唤醒从臂 → 启动 → 失败自动重试一次。 */
export async function b601OneClickTeleopStart(opts?: {
  useCameras?: boolean
  cameraIndices?: number[]
  force?: boolean
  onPhase?: (msg: string) => void
}): Promise<B601Session> {
  const cfg = await getB601Config()
  if (!cfg.calibration_follower || !cfg.calibration_leader) {
    throw new Error(`标定未就绪 — 从臂 ${cfg.robot_id} / 主臂 ${cfg.leader_id}`)
  }

  const launch = async () => {
    opts?.onPhase?.('正在清理并重连…')
    await b601TeleopStopSafe().catch(() => {})
    await b601Probe({ wakeFollower: true }).catch(() => {})
    await b601Recover().catch(() => {})
    opts?.onPhase?.('正在启动遥操…')
    await b601TeleopStart({
      restart: true,
      useCameras: opts?.useCameras ?? false,
      cameraIndices: opts?.cameraIndices,
      robotId: cfg.robot_id,
      leaderId: cfg.leader_id,
      armVariant: cfg.arm_variant,
      followerPort: cfg.follower_port,
      force: opts?.force ?? false,
    })
    return waitForB601TeleopReady({
      timeoutMs: 100_000,
      onTick: (s) => {
        const last = s.log_tail?.[s.log_tail.length - 1]
        if (last) opts?.onPhase?.(last)
      },
    })
  }

  try {
    return await launch()
  } catch (firstErr) {
    const msg = firstErr instanceof Error ? firstErr.message : String(firstErr)
    if (msg.includes('重力补偿')) {
      throw firstErr
    }
    opts?.onPhase?.('首次未成功，正在自动重试…')
    await b601TeleopStopSafe().catch(() => {})
    await b601Recover().catch(() => {})
    await new Promise((r) => setTimeout(r, 1200))
    try {
      return await launch()
    } catch (secondErr) {
      const m2 = secondErr instanceof Error ? secondErr.message : String(secondErr)
      throw new Error(
        `${m2}\n\n若仍失败：再点一次「开始遥操」；或关闭从臂 48V 电源 5 秒后再试。`,
      )
    }
  }
}

export function b601RecordStart(opts: {
  repo_id: string
  single_task: string
  num_episodes?: number
  episode_time_s?: number
  reset_time_s?: number
  camera_indices?: number[]
}) {
  return b601Json<B601Session>('/api/b601/record/start', {
    method: 'POST',
    body: JSON.stringify({
      num_episodes: 5,
      episode_time_s: 30,
      reset_time_s: 5,
      camera_indices: opts.camera_indices ?? loadB601CameraPrefs().indices,
      ...opts,
    }),
  })
}

export interface B601DatasetCheck {
  exists: boolean
  repo_id: string
  path?: string | null
  num_episodes?: number | null
}

export function b601DatasetCheck(repoId: string) {
  return b601Json<B601DatasetCheck>(
    `/api/b601/dataset_check?repo_id=${encodeURIComponent(repoId)}`,
  )
}

export interface B601DatasetListItem {
  repo_id: string
  path: string
  num_episodes?: number | null
  total_frames?: number | null
  robot_type?: string | null
  mtime: number
  size_mb?: number | null
}

export interface B601DatasetList {
  items: B601DatasetListItem[]
  root: string
}

/** List past local LeRobot datasets under HF cache. */
export function b601DatasetsList(prefix?: string) {
  const q = prefix ? `?prefix=${encodeURIComponent(prefix)}` : ''
  return b601Json<B601DatasetList>(`/api/b601/datasets${q}`)
}

/** Upload local LeRobot cache dataset to Hugging Face Hub. */
export function b601DatasetPush(opts: {
  repo_id: string
  hub_repo_id?: string
  token?: string
  private?: boolean
}) {
  return b601Json<B601DatasetPushResult>('/api/b601/dataset/push', {
    method: 'POST',
    body: JSON.stringify(opts),
    timeoutMs: 600_000,
  })
}

export interface B601DatasetFrame {
  ok: boolean
  repo_id: string
  t: number
  episode_index?: number | null
  frame_index?: number | null
  joints: Record<string, number>
  message?: string
}

/** Sample joints for 3D playback — prefer episode_index + t_rel (本条相对秒). */
export function b601DatasetFrame(
  repoId: string,
  t: number,
  opts?: { episode_index?: number; t_rel?: number },
) {
  const q = new URLSearchParams({
    repo_id: repoId,
    t: String(t),
  })
  if (opts?.episode_index != null) q.set('episode_index', String(opts.episode_index))
  if (opts?.t_rel != null) q.set('t_rel', String(opts.t_rel))
  return b601Json<B601DatasetFrame>(`/api/b601/dataset_frame?${q}`, { timeoutMs: 15_000 })
}

export interface B601DatasetVizStatus {
  running: boolean
  repo_id?: string | null
  episode_index?: number | null
  message?: string
  log_tail?: string[]
  last_error?: string | null
}

/** Official lerobot-dataset-viz → Rerun (cameras + state/action). Does not take CAN lock. */
export function b601DatasetVizStart(opts: { repo_id: string; episode_index?: number }) {
  return b601Json<B601DatasetVizStatus>('/api/b601/dataset_viz/start', {
    method: 'POST',
    body: JSON.stringify({
      repo_id: opts.repo_id,
      episode_index: opts.episode_index ?? 0,
    }),
    timeoutMs: 120_000,
  })
}

export function b601DatasetVizStop() {
  return b601Json<B601DatasetVizStatus>('/api/b601/dataset_viz/stop', { method: 'POST' })
}

export function b601DatasetVizStatus() {
  return b601Json<B601DatasetVizStatus>('/api/b601/dataset_viz/status')
}

/** Suggest a fresh 2-part LeRobot repo_id (HF style owner/name). */
export function suggestB601RepoId(prefix = 'b601'): string {
  const ts = new Date()
  const stamp =
    `${ts.getFullYear()}${String(ts.getMonth() + 1).padStart(2, '0')}` +
    `${String(ts.getDate()).padStart(2, '0')}_` +
    `${String(ts.getHours()).padStart(2, '0')}${String(ts.getMinutes()).padStart(2, '0')}`
  return `local/${prefix}-${stamp}`
}

export function normaliseB601RepoId(s: string): string {
  return s
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9._/-]+/g, '-')
    .replace(/-+/g, '-')
    .replace(/(^-|-$)/g, '')
}

/** Exactly one slash — matches LeRobot cache layout + dataset indexer. */
export function isValidB601RepoId(s: string): boolean {
  return /^[a-z0-9._-]+\/[a-z0-9._-]+$/.test(s)
}

export interface B601CameraDevice {
  index: number
  path: string
  name?: string | null
  readable: boolean
  busy?: boolean
  usb_bus?: string | null
}

export interface B601CameraPrefs {
  front: number
  side: number
  top: number | null
  indices: number[]
}

const B601_CAM_PREFS_KEY = 'botversex.b601.cameras'

export function loadB601CameraPrefs(): B601CameraPrefs {
  try {
    const raw = localStorage.getItem(B601_CAM_PREFS_KEY)
    if (raw) {
      const j = JSON.parse(raw) as { front?: number; side?: number }
      const parsed = j as { front?: number; side?: number; top?: number | null }
      const front = Number.isFinite(parsed.front) ? Number(parsed.front) : 4
      const side = Number.isFinite(parsed.side) ? Number(parsed.side) : 6
      const top = Number.isFinite(parsed.top) ? Number(parsed.top) : null
      return {
        front,
        side,
        top,
        indices: [...new Set([front, side, ...(top == null ? [] : [top])])],
      }
    }
  } catch {
    /* ignore */
  }
  // Ice-hockey USB pair as recorded: icspring front + SN0002 side (often 4+6).
  return { front: 4, side: 6, top: null, indices: [4, 6] }
}

export function saveB601CameraPrefs(
  front: number,
  side: number,
  top: number | null = null,
): B601CameraPrefs {
  const prefs: B601CameraPrefs = {
    front,
    side,
    top,
    indices: [...new Set([front, side, ...(top == null ? [] : [top])])],
  }
  try {
    localStorage.setItem(B601_CAM_PREFS_KEY, JSON.stringify({ front, side, top }))
  } catch {
    /* ignore */
  }
  return prefs
}

export function getB601Cameras() {
  return b601Json<B601CameraDevice[]>('/api/b601/cameras')
}

export function b601RecordStop() {
  return b601Json<B601Session>('/api/b601/record/stop', { method: 'POST' })
}

export function b601RecordStatus() {
  return b601Json<B601Session>('/api/b601/record/status')
}

/** Skip remaining episode/reset (LeRobot Right Arrow). */
export function b601RecordSkip() {
  return b601Json<B601Session>('/api/b601/record/skip', { method: 'POST' })
}

/** Re-record current episode (LeRobot Left Arrow). */
export function b601RecordRerecord() {
  return b601Json<B601Session>('/api/b601/record/rerecord', { method: 'POST' })
}

export type B601EpisodeVerdict = 'ok' | 'bad' | null

export interface B601EpisodeVideo {
  key: string
  file: string
  url: string
  from_timestamp?: number
  to_timestamp?: number
}

export interface B601EpisodeItem {
  episode_index: number
  length: number
  verdict?: B601EpisodeVerdict | string | null
  marked_at?: number | null
  videos: B601EpisodeVideo[]
}

export interface B601DatasetEpisodes {
  repo_id: string
  path?: string | null
  num_episodes: number
  bad_count: number
  unmarked_count: number
  episodes: B601EpisodeItem[]
}

export function b601DatasetEpisodes(repoId: string) {
  return b601Json<B601DatasetEpisodes>(
    `/api/b601/dataset/episodes?repo_id=${encodeURIComponent(repoId)}`,
    { timeoutMs: 60_000 },
  )
}

export function b601RecordMark(opts: {
  repo_id: string
  episode_index: number
  verdict: 'ok' | 'bad' | 'clear'
}) {
  return b601Json<{
    ok: boolean
    repo_id: string
    episode_index: number
    verdict?: string | null
    message?: string
  }>('/api/b601/record/mark', {
    method: 'POST',
    body: JSON.stringify(opts),
  })
}

export function b601DatasetEpisodeDelete(opts: {
  repo_id: string
  episode_index?: number
  episode_indices?: number[]
  delete_all_bad?: boolean
}) {
  return b601Json<{
    ok: boolean
    repo_id: string
    deleted: number[]
    num_episodes: number
    message?: string
  }>('/api/b601/dataset/episode/delete', {
    method: 'POST',
    body: JSON.stringify(opts),
    timeoutMs: 600_000,
  })
}

export interface B601DatasetVideo {
  key: string
  file: string
  url: string
}

export interface B601DatasetVideos {
  repo_id: string
  path?: string | null
  num_episodes?: number | null
  videos: B601DatasetVideo[]
}

export function b601DatasetVideos(repoId: string) {
  return b601Json<B601DatasetVideos>(
    `/api/b601/dataset_videos?repo_id=${encodeURIComponent(repoId)}`,
  )
}

export function b601InferenceStart(
  policyPath: string,
  singleTask = '冰球游戏，将对方击过来的红色圆盘击回去',
  opts?: {
    cameraIndices?: number[]
    /** 'remote' = LAN sidecar (recommended); 'local' = lerobot-record on this laptop. */
    backend?: 'remote' | 'local' | 'gb10'
    sidecarUrl?: string
    /** Optional RemoteComputeNode id; resolves sidecar_url + default model path from config. */
    nodeId?: string
  },
) {
  // 'gb10' is the legacy spelling; normalize to 'remote'.
  const backend = opts?.backend === 'gb10' ? 'remote' : opts?.backend ?? 'remote'
  return b601Json<B601Session>('/api/b601/inference/start', {
    method: 'POST',
    body: JSON.stringify({
      policy_path: policyPath,
      single_task: singleTask,
      // Laptop-only cameras. Prefer caller / saved UI prefs (front, side).
      camera_indices: opts?.cameraIndices ?? loadB601CameraPrefs().indices.slice(0, 2),
      backend,
      sidecar_url: opts?.sidecarUrl,
      node_id: opts?.nodeId,
    }),
  })
}

export function b601InferenceStop() {
  return b601Json<B601Session>('/api/b601/inference/stop', { method: 'POST' })
}

/** Emergency stop for GB10 deploy: cut torque first, then stop inference loop. */
export async function b601InferenceStopSafe() {
  void b601Disable().catch(() => {})
  return b601InferenceStop()
}

export function b601InferenceStatus() {
  return b601Json<B601Session>('/api/b601/inference/status')
}

export interface B601SidecarStatus {
  ok: boolean
  sidecar_url?: string
  loaded?: boolean
  model_key?: string | null
  device?: string | null
  error?: string
  [key: string]: unknown
}

export function b601SidecarStatus(sidecarUrl?: string, nodeId?: string) {
  const params = new URLSearchParams()
  if (sidecarUrl) params.set('sidecar_url', sidecarUrl)
  if (nodeId) params.set('node_id', nodeId)
  const q = params.toString() ? `?${params.toString()}` : ''
  return b601Json<B601SidecarStatus>(`/api/b601/inference/sidecar_status${q}`, { timeoutMs: 8_000 })
}

export function b601SidecarLoadModel(opts: {
  modelKey: string
  taskPrompt?: string
  sidecarUrl?: string
  nodeId?: string
}) {
  return b601Json<{ ok: boolean; model_key?: string; error?: string }>('/api/b601/inference/load_model', {
    method: 'POST',
    body: JSON.stringify({
      model_key: opts.modelKey,
      task_prompt: opts.taskPrompt,
      sidecar_url: opts.sidecarUrl,
      node_id: opts.nodeId,
    }),
    timeoutMs: 620_000,
  })
}

export function b601SyncModelToRemote(opts: {
  modelId?: string
  jobId?: string
  /** RemoteComputeNode id; if omitted, the default node is used. */
  nodeId?: string
  /** Optional override for the remote model directory. */
  remoteDir?: string
  load?: boolean
}) {
  return b601Json<{ ok: boolean; pid?: number; log?: string; status_file?: string; message?: string }>(
    '/api/b601/inference/sync_model',
    {
      method: 'POST',
      body: JSON.stringify({
        model_id: opts.modelId,
        job_id: opts.jobId,
        node_id: opts.nodeId,
        remote_dir: opts.remoteDir,
        load: opts.load ?? true,
      }),
      timeoutMs: 30_000,
    },
  )
}

/** @deprecated Use b601SyncModelToRemote (same backend, new name). */
export function b601SyncModelToGb10(opts: Parameters<typeof b601SyncModelToRemote>[0]) {
  return b601SyncModelToRemote(opts)
}

export function b601SyncModelStatus() {
  return b601Json<{
    ok: boolean
    phase?: string
    model_id?: string
    model_key?: string
    remote_dir?: string
    error?: string
  }>('/api/b601/inference/sync_status')
}

/** Classify training/model labels for deploy UI. */
export function b601ModelKind(label: string | null | undefined): 'smoke' | 'full' | 'other' {
  const s = (label || '').toLowerCase()
  if (s.includes('smoke')) return 'smoke'
  if (s.includes('icehockey-v1') || s.includes('icehockey_v1') || s.includes('b601-dm-icehockey-v1')) {
    return 'full'
  }
  return 'other'
}

export function b601CalibrateStart(
  target: 'follower' | 'leader',
  opts?: { robotId?: string; leaderId?: string },
) {
  return b601Json<B601Session>('/api/b601/calibrate/start', {
    method: 'POST',
    body: JSON.stringify({
      target,
      robot_id: opts?.robotId,
      leader_id: opts?.leaderId,
    }),
  })
}

export function b601CalibrateContinue() {
  return b601Json<B601Session>('/api/b601/calibrate/continue', { method: 'POST' })
}

export function b601CalibrateStop() {
  return b601Json<B601Session>('/api/b601/calibrate/stop', { method: 'POST' })
}

export function b601CalibrateStatus() {
  return b601Json<B601Session>('/api/b601/calibrate/status')
}

export function getB601Joints() {
  return b601Json<{ ok: boolean; teleop_running: boolean; joints: Record<string, number> }>(
    '/api/b601/joints',
    { timeoutMs: 45_000 },
  )
}

export async function b601Snapshot(opts?: { repo_id?: string; label?: string }) {
  const response = await agentFetch('/api/b601/snapshot', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      repo_id: opts?.repo_id,
      label: opts?.label ?? 'lab_snapshot',
    }),
    timeoutMs: 120_000,
  })
  if (!response.ok) {
    const text = await response.text()
    throw new Error(friendlyB601Error(text))
  }
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `b601_snapshot_${Date.now()}.zip`
  a.click()
  URL.revokeObjectURL(url)
}

export function getB601UrdfHealth() {
  return b601Json<{ ok: boolean; mesh_total: number; mesh_present: number; missing: string[] }>(
    '/api/b601/urdf/health',
  )
}

export function b601GatewayStart() {
  return b601Json<{ running: boolean }>('/api/b601/gateway/start', { method: 'POST' })
}

export function b601GatewayStop() {
  return b601Json<{ running: boolean }>('/api/b601/gateway/stop', { method: 'POST' })
}

export const B601_WIZARD_DONE_KEY = 'botversex.setup.b601_rs.v1.wizard_completed'

export function isB601WizardComplete(): boolean {
  if (typeof window === 'undefined') return false
  return window.localStorage.getItem(B601_WIZARD_DONE_KEY) === 'true'
}

export function markB601WizardComplete() {
  window.localStorage.setItem(B601_WIZARD_DONE_KEY, 'true')
}
