import { agentFetch } from './localAgent'

export type ReachyMotorMode = 'enabled' | 'disabled' | 'gravity_compensation'

/**
 * T1-1: 模块级虚拟模式开关。
 *
 * Reachy 虚拟模式（`?guide=virtual`）跑在云端 realtime 的内存状态机上，所有 reachy
 * 调用（move / state / record / virtual）都必须走同源云端，绝不能被 localStorage
 * 里残留的 Local Agent URL 劫持到 https://localhost:8002。
 *
 * 进入虚拟模式时由 RobotReachyMini 调用 setReachyVirtualActive(true)；
 * 退出虚拟模式或真机 daemon 上线时调用 setReachyVirtualActive(false)。
 *
 * 同时首次加载时根据 URL `?guide=virtual` 自动开启，确保第一次 getReachyVirtualStatus
 * 之前的 move/state 调用也走同源。
 */
let _reachyVirtualActive = false
if (typeof window !== 'undefined') {
  try {
    const url = new URL(window.location.href)
    if (url.searchParams.get('guide') === 'virtual') {
      _reachyVirtualActive = true
    }
  } catch {
    // ignore
  }
}

export function setReachyVirtualActive(active: boolean): void {
  _reachyVirtualActive = active
}

export function isReachyVirtualActive(): boolean {
  return _reachyVirtualActive
}

export interface ReachyPose {
  x?: number
  y?: number
  z?: number
  roll?: number
  pitch?: number
  yaw?: number
}

export interface ReachyGotoRequest {
  head_pose?: ReachyPose
  antennas?: [number, number]
  body_yaw?: number
  duration: number
  interpolation?: 'minimum_jerk' | 'minjerk' | 'linear'
}

export interface ReachyMoveResponse {
  uuid?: string
  status?: string
  [key: string]: unknown
}

export interface ReachyDaemonStatus {
  status?: string
  running?: boolean
  [key: string]: unknown
}

export interface ReachyMotorStatus {
  mode?: ReachyMotorMode | string
  [key: string]: unknown
}

export interface ReachySerialStatus {
  port: string
  exists: boolean
  readable: boolean
  writable: boolean
  openable: boolean | null
  error: string | null
}

export interface ReachyDaemonHttpStatus {
  base: string
  ok: boolean | null
  status_code?: number | null
  error: string | null
}

export interface ReachyLocalDaemonStatus {
  transport: 'usb_serial' | string
  service: 'local_daemon' | string
  serial_port: string
  sdk_path: string
  python: string
  pythonpath?: string
  log_file?: string
  daemon_http: ReachyDaemonHttpStatus
  managed_process: {
    running: boolean
    pid: number | null
    returncode: number | null
  }
}

export interface ReachyVirtualStatus {
  active: boolean
  motor_mode?: string
  playback_count?: number
  recording?: boolean
}

export interface ReachyRecordFrame {
  head: ReachyPose | number[][]
  antennas: [number, number]
  body_yaw: number
}

export interface ReachyRecordStatus {
  active: boolean
  captured?: boolean
  name: string
  sample_hz: number
  sample_count: number
  elapsed_s: number
  virtual: boolean
  compliant?: boolean
  control_mode?: string | null
  latest_frame?: ReachyRecordFrame | null
}

export interface ReachyRecordStartResponse {
  ok: boolean
  active: boolean
  name: string
  display_name?: string
  sample_hz: number
  category: string
  compliance?: {
    requested: boolean
    applied: boolean
    mode?: string
    previous_mode?: string | null
    detail?: Record<string, unknown>
  }
}

export interface ReachyRecordStopResponse {
  ok: boolean
  move_name: string
  display_name?: string
  category: string
  path: string
  duration_s: number
  sample_count: number
}

export interface ReachyPingResponse {
  ok: boolean
  transport: 'usb_serial' | string
  service: 'local_daemon' | string
  serial: ReachySerialStatus
  daemon_http: ReachyDaemonHttpStatus
  local_daemon: ReachyLocalDaemonStatus
  virtual?: ReachyVirtualStatus
  recording?: {
    active: boolean
    name: string
    sample_count: number
  }
  resolution: {
    host: string
    port: number
    ips: string[]
    resolve_error?: string
  }
  hints: string[]
  log_tail?: string[]
}

export interface ReachyLocalDaemonActionResponse extends ReachyLocalDaemonStatus {
  ok: boolean
  message: string
  command?: string[]
}

export interface ReachyFullState {
  control_mode?: ReachyMotorMode | string
  head_pose?: ReachyPose | number[] | number[][]
  target_head_pose?: ReachyPose | number[] | number[][]
  head_joints?: number[]
  target_head_joints?: number[]
  body_yaw?: number
  target_body_yaw?: number
  antennas_position?: number[]
  target_antennas_position?: number[]
  passive_joints?: number[] | null
  doa?: unknown
  timestamp?: string
  [key: string]: unknown
}

/** Lightweight probe used by Reachy UI to detect Vite → realtime proxy failures (e.g. HTTP/HTTPS mismatch). */
export async function probeRealtimeHealth(): Promise<{ ok: boolean; status: number }> {
  try {
    const response = await agentFetch('/api/setup/health')
    return { ok: response.ok, status: response.status }
  } catch {
    return { ok: false, status: 0 }
  }
}

async function reachyJson<T>(
  path: string,
  init?: RequestInit & { timeoutMs?: number; forceSameOrigin?: boolean },
): Promise<T> {
  const timeoutMs = init?.timeoutMs
  // T1-1: 虚拟模式激活时，所有 reachy 调用都强制同源。调用方仍可显式覆盖。
  const forceSameOrigin = init?.forceSameOrigin ?? _reachyVirtualActive
  const { timeoutMs: _drop, forceSameOrigin: _drop2, ...rest } = init ?? {}
  let response: Response
  try {
    response = await agentFetch(path, {
      ...rest,
      ...(timeoutMs != null ? { timeoutMs } : {}),
      ...(forceSameOrigin != null ? { forceSameOrigin } : {}),
      headers: {
        ...(rest.body ? { 'Content-Type': 'application/json' } : {}),
        ...rest.headers,
      },
    })
  } catch (e) {
    if (e instanceof DOMException && e.name === 'TimeoutError') {
      const longOp = /\/conversation\/(start|restart)|\/seeed-conversation\/(start|setup|install)/.test(
        path,
      )
      throw new Error(
        longOp
          ? '启动对话超时（首次安装官方 App 可能需要几分钟）。请看对话面板状态，或稍后重试；不要反复连点。'
          : '实时服务未响应（超时），请确认 apps/realtime 正在运行',
      )
    }
    if (e instanceof TypeError) {
      throw new Error('无法连接实时服务，请确认网络或 apps/realtime 是否启动')
    }
    throw e
  }

  if (!response.ok) {
    if (response.status === 502) {
      throw new Error(
        '开发代理无法连接实时服务（502）。请用 HTTP 启动：cd apps/realtime && .venv/bin/python run_api.py --http',
      )
    }
    let detail = `${response.status} ${response.statusText}`
    try {
      const body = await response.json()
      detail = body?.detail?.message ?? body?.detail ?? body?.message ?? detail
    } catch {
      // Keep the HTTP fallback if the daemon returned plain text.
    }
    throw new Error(String(detail))
  }

  return response.json() as Promise<T>
}

export function getReachyState(): Promise<ReachyFullState> {
  return reachyJson<ReachyFullState>(
    '/api/reachy/state/full?with_head_joints=true&with_body_yaw=true&with_antenna_positions=true&with_control_mode=true',
  )
}

export function getMotorStatus(): Promise<ReachyMotorStatus> {
  return reachyJson<ReachyMotorStatus>('/api/reachy/motors/status')
}

export function setMotorMode(mode: ReachyMotorMode): Promise<{ status?: string }> {
  return reachyJson<{ status?: string }>(`/api/reachy/motors/set_mode/${mode}`, {
    method: 'POST',
  })
}

export function moveGoto(payload: ReachyGotoRequest): Promise<ReachyMoveResponse> {
  return reachyJson<ReachyMoveResponse>('/api/reachy/move/goto', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export interface ReachyComposeMoveResponse {
  ok: boolean
  move_name: string
  display_name?: string
  category: string
  path: string
  duration_s: number
  sample_count: number
}

export interface ReachyMoveJsonPayload {
  description?: string
  display_name?: string
  time: number[]
  set_target_data: Array<{
    head: ReachyPose | number[][]
    antennas: [number, number]
    body_yaw: number
  }>
}

export function composeReachyMove(payload: {
  name: string
  display_name?: string
  description?: string
  time: number[]
  set_target_data: ReachyMoveJsonPayload['set_target_data']
}): Promise<ReachyComposeMoveResponse> {
  return reachyJson<ReachyComposeMoveResponse>('/api/reachy/moves/compose', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function loadReachyMoveJson(category: string, moveName: string): Promise<ReachyMoveJsonPayload> {
  return reachyJson<ReachyMoveJsonPayload>(
    `/api/reachy/moves/json/${encodeURIComponent(category)}/${encodeURIComponent(moveName)}`,
  )
}

export function deleteReachyMove(category: string, moveName: string): Promise<{ ok: boolean; move_name: string }> {
  return reachyJson<{ ok: boolean; move_name: string }>(
    `/api/reachy/moves/${encodeURIComponent(category)}/${encodeURIComponent(moveName)}`,
    { method: 'DELETE' },
  )
}

export function getLocalCategories(): Promise<string[]> {
  return reachyJson<string[]>('/api/reachy/move/local-categories')
}

export function getLocalMoves(category: string): Promise<string[]> {
  return reachyJson<string[]>(`/api/reachy/move/local-moves/list/${encodeURIComponent(category)}`)
}

export interface ReachyMoveJson {
  description?: string
  display_name?: string
  time: number[]
  set_target_data: ReachyRecordFrame[]
}

export function getReachyMoveJson(category: string, moveName: string): Promise<ReachyMoveJson> {
  return reachyJson<ReachyMoveJson>(
    `/api/reachy/moves/json/${encodeURIComponent(category)}/${encodeURIComponent(moveName)}`,
  )
}

export function playLocalMove(name: string): Promise<ReachyMoveResponse> {
  return reachyJson<ReachyMoveResponse>(
    `/api/reachy/move/play/local-move/${encodeURIComponent(name)}`,
    { method: 'POST' },
  )
}

export function stopMove(uuid: string | null): Promise<{ status?: string }> {
  return reachyJson<{ status?: string }>('/api/reachy/move/stop', {
    method: 'POST',
    body: JSON.stringify({ uuid }),
  })
}

export function getDaemonStatus(): Promise<ReachyDaemonStatus> {
  return reachyJson<ReachyDaemonStatus>('/api/reachy/daemon/status')
}

export function getReachyPing(): Promise<ReachyPingResponse> {
  return reachyJson<ReachyPingResponse>('/api/reachy/ping')
}

export function getReachyLocalDaemonStatus(): Promise<ReachyLocalDaemonStatus> {
  return reachyJson<ReachyLocalDaemonStatus>('/api/reachy/local-daemon/status')
}

export function startReachyLocalDaemon(): Promise<ReachyLocalDaemonActionResponse> {
  return reachyJson<ReachyLocalDaemonActionResponse>('/api/reachy/local-daemon/start', {
    method: 'POST',
  })
}

export function stopReachyLocalDaemon(): Promise<ReachyLocalDaemonActionResponse> {
  return reachyJson<ReachyLocalDaemonActionResponse>('/api/reachy/local-daemon/stop', {
    method: 'POST',
  })
}

export function wakeUp(): Promise<ReachyMoveResponse> {
  return reachyJson<ReachyMoveResponse>('/api/reachy/move/play/wake_up', {
    method: 'POST',
  })
}

export function gotoSleep(): Promise<ReachyMoveResponse> {
  return reachyJson<ReachyMoveResponse>('/api/reachy/move/play/goto_sleep', {
    method: 'POST',
  })
}

export function getReachyRecordStatus(): Promise<ReachyRecordStatus> {
  return reachyJson<ReachyRecordStatus>('/api/reachy/record/status')
}

export function startReachyRecord(payload?: {
  name?: string
  description?: string
  sample_hz?: number
  compliant?: boolean
}): Promise<ReachyRecordStartResponse> {
  return reachyJson<ReachyRecordStartResponse>('/api/reachy/record/start', {
    method: 'POST',
    body: JSON.stringify(payload ?? {}),
  })
}

export function stopReachyRecord(payload?: {
  name?: string
  display_name?: string
}): Promise<ReachyRecordStopResponse> {
  return reachyJson<ReachyRecordStopResponse>('/api/reachy/record/stop', {
    method: 'POST',
    body: JSON.stringify(payload ?? {}),
  })
}

export function stopReachyRecordCapture(): Promise<{
  ok: boolean
  captured: boolean
  elapsed_s: number
  sample_count: number
}> {
  return reachyJson('/api/reachy/record/capture/stop', { method: 'POST' })
}

export function resumeReachyRecordCapture(): Promise<{
  ok: boolean
  active: boolean
  elapsed_s: number
  sample_count: number
}> {
  return reachyJson('/api/reachy/record/capture/resume', { method: 'POST' })
}

export function discardReachyRecord(): Promise<{ ok: boolean }> {
  return reachyJson('/api/reachy/record/discard', { method: 'POST' })
}

export function getReachyVirtualStatus(): Promise<ReachyVirtualStatus> {
  // T1-1: 虚拟模式是云端 realtime 的内存状态机，必须走同源云端，不能被 localStorage
  // 里残留的 Local Agent URL 劫持到 https://localhost:8002。
  return reachyJson<ReachyVirtualStatus>('/api/reachy/virtual/status', { forceSameOrigin: true })
}

export function startReachyVirtual(): Promise<{ ok: boolean; active: boolean; message: string }> {
  return reachyJson<{ ok: boolean; active: boolean; message: string }>('/api/reachy/virtual/start', {
    method: 'POST',
    forceSameOrigin: true,
  })
}

export function stopReachyVirtual(): Promise<{ ok: boolean; active: boolean; message: string }> {
  return reachyJson<{ ok: boolean; active: boolean; message: string }>('/api/reachy/virtual/stop', {
    method: 'POST',
    forceSameOrigin: true,
  })
}

// ============== M21: Apps / Volume / DoA / Daemon lifecycle ==============

export type ReachyAppSourceKind = 'hf_space' | 'installed' | 'local'

export interface ReachyApp {
  name: string
  description?: string
  url?: string
  source_kind: ReachyAppSourceKind | string
  extra?: Record<string, unknown>
  [key: string]: unknown
}

export interface ReachyAppStatus {
  name?: string
  pid?: number | null
  running?: boolean
  started_at?: string | null
  returncode?: number | null
  [key: string]: unknown
}

export interface ReachyJobInfo {
  job_id?: string
  command?: string
  status?: 'pending' | 'running' | 'completed' | 'failed' | string
  logs?: string[]
  returncode?: number | null
  error?: string | null
  [key: string]: unknown
}

export interface ReachyAppUpdateStatus {
  app_name: string
  space_id: string
  installed_sha: string
  latest_sha: string
  update_available: boolean
  last_modified?: string | null
}

export interface ReachyAppUpdatesResponse {
  apps_with_updates: ReachyAppUpdateStatus[]
  apps_checked: number
  apps_skipped: number
}

export interface ReachyVolumeResponse {
  volume: number
  platform: string
  device: string
}

export interface ReachyTestSoundResponse {
  status: 'ok' | 'busy' | string
  message: string
}

export interface ReachyDoAInfo {
  angle: number
  speech_detected: boolean
}

export interface ReachyDaemonState {
  robot_name?: string
  state?: string
  wireless_version?: boolean
  desktop_app_daemon?: boolean
  simulation_enabled?: boolean
  mockup_sim_enabled?: boolean
  backend_status?: {
    ready?: boolean
    motor_control_mode?: string
    last_alive?: string | null
    control_loop_stats?: Record<string, unknown>
    [key: string]: unknown
  }
  [key: string]: unknown
}

export interface ReachyLocalDaemonStartResponse extends ReachyLocalDaemonActionResponse {
  audio_fallback_used?: boolean
  audio_warning?: string | null
}

// ---- Apps ----

export function listReachyApps(): Promise<ReachyApp[]> {
  return reachyJson<ReachyApp[]>('/api/reachy/apps/list-available')
}

export function listReachyAppsBySource(source: ReachyAppSourceKind): Promise<ReachyApp[]> {
  return reachyJson<ReachyApp[]>(`/api/reachy/apps/list-available/${encodeURIComponent(source)}`)
}

export function installReachyApp(app: ReachyApp): Promise<{ job_id: string }> {
  return reachyJson<{ job_id: string }>('/api/reachy/apps/install', {
    method: 'POST',
    body: JSON.stringify(app),
  })
}

export function installPrivateReachySpace(spaceId: string): Promise<{ job_id: string }> {
  return reachyJson<{ job_id: string }>('/api/reachy/apps/install-private-space', {
    method: 'POST',
    body: JSON.stringify({ space_id: spaceId }),
  })
}

export function removeReachyApp(appName: string): Promise<{ job_id: string }> {
  return reachyJson<{ job_id: string }>(
    `/api/reachy/apps/remove/${encodeURIComponent(appName)}`,
    { method: 'POST' },
  )
}

export function startReachyApp(appName: string): Promise<ReachyAppStatus> {
  return reachyJson<ReachyAppStatus>(
    `/api/reachy/apps/start-app/${encodeURIComponent(appName)}`,
    { method: 'POST' },
  )
}

export function restartCurrentReachyApp(): Promise<ReachyAppStatus> {
  return reachyJson<ReachyAppStatus>('/api/reachy/apps/restart-current-app', {
    method: 'POST',
  })
}

export function stopCurrentReachyApp(): Promise<void> {
  return reachyJson<void>('/api/reachy/apps/stop-current-app', { method: 'POST' })
}

export function getCurrentReachyAppStatus(): Promise<ReachyAppStatus | null> {
  return reachyJson<ReachyAppStatus | null>('/api/reachy/apps/current-app-status')
}

export function getReachyJobStatus(jobId: string): Promise<ReachyJobInfo> {
  return reachyJson<ReachyJobInfo>(`/api/reachy/apps/job-status/${encodeURIComponent(jobId)}`)
}

export function checkReachyAppUpdates(force = false): Promise<ReachyAppUpdatesResponse> {
  const qs = force ? '?force=true' : ''
  return reachyJson<ReachyAppUpdatesResponse>(`/api/reachy/apps/check-updates${qs}`)
}

export function updateReachyApp(appName: string): Promise<{ job_id: string }> {
  return reachyJson<{ job_id: string }>(
    `/api/reachy/apps/update/${encodeURIComponent(appName)}`,
    { method: 'POST' },
  )
}

// ---- Volume ----

export function getReachySpeakerVolume(): Promise<ReachyVolumeResponse> {
  return reachyJson<ReachyVolumeResponse>('/api/reachy/volume/current')
}

export function setReachySpeakerVolume(volume: number): Promise<ReachyVolumeResponse> {
  return reachyJson<ReachyVolumeResponse>('/api/reachy/volume/set', {
    method: 'POST',
    body: JSON.stringify({ volume: Math.max(0, Math.min(100, Math.round(volume))) }),
  })
}

export function playReachyTestSound(): Promise<ReachyTestSoundResponse> {
  return reachyJson<ReachyTestSoundResponse>('/api/reachy/volume/test-sound', {
    method: 'POST',
  })
}

export function getReachyMicVolume(): Promise<ReachyVolumeResponse> {
  return reachyJson<ReachyVolumeResponse>('/api/reachy/volume/microphone/current')
}

export function setReachyMicVolume(volume: number): Promise<ReachyVolumeResponse> {
  return reachyJson<ReachyVolumeResponse>('/api/reachy/volume/microphone/set', {
    method: 'POST',
    body: JSON.stringify({ volume: Math.max(0, Math.min(100, Math.round(volume))) }),
  })
}

// ---- Direction of Arrival ----

export function getReachyDoA(): Promise<ReachyDoAInfo | null> {
  return reachyJson<ReachyDoAInfo | null>('/api/reachy/state/doa')
}

// ============== M23: Camera + head tracker ==============

export interface ReachyCameraDevice {
  index: number
  path?: string
  width?: number
  height?: number
  fps?: number
  backend?: string
  readable?: boolean
  busy?: boolean
  [key: string]: unknown
}

export interface ReachyHeadTrackerStatus {
  ok: boolean
  running: boolean
  device: number | null
  fps: number
  last_face_at: number
  last_target: { yaw: number; pitch: number } | null
  last_error: string | null
}

export function listReachyCameras(): Promise<{ ok: boolean; devices: ReachyCameraDevice[] }> {
  return reachyJson<{ ok: boolean; devices: ReachyCameraDevice[] }>('/api/reachy/camera/devices')
}

export function reachyCameraSnapshotUrl(device = 0, w = 640, h = 480): string {
  return `/api/reachy/camera/snapshot?device=${device}&w=${w}&h=${h}`
}

export function startReachyHeadTracker(device = 0): Promise<{ ok: boolean; device: number; fps: number }> {
  return reachyJson<{ ok: boolean; device: number; fps: number }>(
    `/api/reachy/camera/head-tracker/start?device=${device}`,
    { method: 'POST' },
  )
}

export function stopReachyHeadTracker(): Promise<{ ok: boolean; running: boolean }> {
  return reachyJson<{ ok: boolean; running: boolean }>(
    '/api/reachy/camera/head-tracker/stop',
    { method: 'POST' },
  )
}

export function getReachyHeadTrackerStatus(): Promise<ReachyHeadTrackerStatus> {
  return reachyJson<ReachyHeadTrackerStatus>('/api/reachy/camera/head-tracker/status')
}

// ============== M24: Official HF recorded-move datasets ==============

export interface ReachyRecordedDataset {
  dataset: string
  kind: 'emotions' | 'dances' | string
  display_name: string
  description: string
}

export function listKnownReachyRecordedDatasets(): Promise<{ ok: boolean; datasets: ReachyRecordedDataset[] }> {
  return reachyJson<{ ok: boolean; datasets: ReachyRecordedDataset[] }>(
    '/api/reachy/move/recorded-move-datasets',
  )
}

export function listReachyRecordedMoves(dataset: string): Promise<string[]> {
  return reachyJson<string[]>(
    `/api/reachy/move/recorded-move-datasets/list/${encodeURIComponent(dataset)}`,
  )
}

export function playReachyRecordedMove(dataset: string, move: string): Promise<unknown> {
  return reachyJson<unknown>(
    `/api/reachy/move/recorded-move-datasets/play/${encodeURIComponent(dataset)}/${encodeURIComponent(move)}`,
    { method: 'POST' },
  )
}

// ---- Full daemon lifecycle ----

export function startReachyDaemon(wakeUp = true): Promise<{ job_id: string }> {
  return reachyJson<{ job_id: string }>(
    `/api/reachy/daemon/start?wake_up=${wakeUp ? 'true' : 'false'}`,
    { method: 'POST' },
  )
}

export function stopReachyDaemon(gotoSleep = true): Promise<{ job_id: string }> {
  return reachyJson<{ job_id: string }>(
    `/api/reachy/daemon/stop?goto_sleep=${gotoSleep ? 'true' : 'false'}`,
    { method: 'POST' },
  )
}

export function restartReachyDaemon(): Promise<{ job_id: string }> {
  return reachyJson<{ job_id: string }>('/api/reachy/daemon/restart', { method: 'POST' })
}

export function getReachyDaemonState(): Promise<ReachyDaemonState> {
  return reachyJson<ReachyDaemonState>('/api/reachy/daemon/status')
}

// ============== M22: Conversation App lifecycle ==============

export type ReachyConversationBackend = 'huggingface' | 'openai' | 'gemini'
export type ReachyHeadTracker = 'yolo' | 'mediapipe'

export interface ReachyConversationBackendInfo {
  label: string
  requires_key: boolean
  key_env?: string
  default_model?: string | null
  key_hint?: string
  env?: Record<string, string>
}

export interface ReachyConversationEnvTemplate {
  backends: Record<ReachyConversationBackend, ReachyConversationBackendInfo>
  cli_flags: {
    head_tracker?: { options: string[]; requires_extra?: boolean }
    local_vision?: { requires_extra?: string; default_model?: string }
    gradio?: { default: boolean; port: number }
    no_camera?: { default: boolean }
  }
  app_info: {
    name: string
    hf_url: string
    hf_id: string
    description: string
  }
}

export interface ReachyConversationStatus {
  running: boolean
  state: 'stopped' | 'installing' | 'starting' | 'running' | 'error' | string
  backend?: ReachyConversationBackend | null
  model?: string | null
  head_tracker?: ReachyHeadTracker | null
  local_vision: boolean
  gradio: boolean
  no_camera: boolean
  pid?: number | null
  started_at?: number | null
  returncode?: number | null
  error?: string | null
  command?: string[] | null
  gradio_url?: string | null
  app_installed: boolean
  log_tail: string[]
}

export interface ReachyConversationStartRequest {
  provider?: ReachyConversationProvider
  backend?: ReachyConversationBackend
  api_key?: string | null
  model?: string | null
  hf_token?: string | null
  head_tracker?: ReachyHeadTracker | null
  local_vision?: boolean
  gradio?: boolean
  no_camera?: boolean
  robot_name?: string | null
  debug?: boolean
  auto_install?: boolean
}

export interface ReachyConversationStartResponse {
  ok: boolean
  message: string
  pid: number
  command: string[]
  backend: ReachyConversationBackend
  gradio_url?: string | null
  log_file: string
}

export function getReachyConversationEnvTemplate(): Promise<ReachyConversationEnvTemplate> {
  return reachyJson<ReachyConversationEnvTemplate>('/api/reachy/conversation/env-template')
}

export function getReachyConversationStatus(): Promise<ReachyConversationStatus> {
  return reachyJson<ReachyConversationStatus>('/api/reachy/conversation/status')
}

/** Official Conversation App install + audio daemon restart can take minutes. */
const CONVERSATION_START_TIMEOUT_MS = 300_000

export function startReachyConversation(
  req: ReachyConversationStartRequest,
): Promise<ReachyConversationStartResponse> {
  return reachyJson<ReachyConversationStartResponse>('/api/reachy/conversation/start', {
    method: 'POST',
    body: JSON.stringify({ provider: 'official', gradio: true, no_camera: true, ...req }),
    timeoutMs: CONVERSATION_START_TIMEOUT_MS,
  })
}

export function stopReachyConversation(): Promise<{ ok: boolean; message: string; returncode?: number | null }> {
  return reachyJson<{ ok: boolean; message: string; returncode?: number | null }>(
    '/api/reachy/conversation/stop',
    { method: 'POST' },
  )
}

export function restartReachyConversation(
  req: ReachyConversationStartRequest,
): Promise<ReachyConversationStartResponse> {
  return reachyJson<ReachyConversationStartResponse>('/api/reachy/conversation/restart', {
    method: 'POST',
    body: JSON.stringify({ provider: 'official', gradio: true, ...req }),
    timeoutMs: CONVERSATION_START_TIMEOUT_MS,
  })
}

export function getReachyConversationLogs(tail = 80): Promise<{
  lines: string[]
  log_file: string
  running: boolean
}> {
  return reachyJson<{ lines: string[]; log_file: string; running: boolean }>(
    `/api/reachy/conversation/logs?tail=${encodeURIComponent(tail)}`,
  )
}

export function listReachyConversationApps(): Promise<ReachyApp[]> {
  return reachyJson<ReachyApp[]>('/api/reachy/conversation/apps')
}

// ============== M26: BotverseX 平台原生聊天 (零 Key 路线) ==============

export type ReachyChatState = 'idle' | 'listening' | 'thinking' | 'speaking'
export type ReachyConversationProvider = 'official' | 'botversex' | 'openai_pro' | 'gemini_pro'

export interface ReachyChatStatus {
  state: ReachyChatState
  last_user_message: string | null
  last_reply: string | null
  last_actions: Array<Record<string, string>> | null
  started_at: number | null
  tts_available: boolean
  tts_binary: string | null
}

export interface ReachyChatSendRequest {
  message: string
  history?: Array<{ role: string; content: string }>
  page?: string
  speak?: boolean
  wobble?: boolean
}

export interface ReachyChatSendResponse {
  reply: string
  actions: Array<Record<string, string>> | null
  state: ReachyChatState
  tts_available: boolean
  tts_played: boolean
  error: string | null
}

export interface ReachyChatTtsAvailability {
  available: Record<string, boolean>
  any_available: boolean
  active_binary: string | null
  piper_voice_configured: boolean
  install_hints: Record<string, string>
}

export function getReachyChatStatus(): Promise<ReachyChatStatus> {
  return reachyJson<ReachyChatStatus>('/api/reachy/chat/status')
}

export function sendReachyChatMessage(
  req: ReachyChatSendRequest,
  authorization?: string | null,
): Promise<ReachyChatSendResponse> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (authorization) headers['Authorization'] = authorization
  return reachyJson<ReachyChatSendResponse>('/api/reachy/chat/send', {
    method: 'POST',
    body: JSON.stringify(req),
    headers,
  })
}

export function speakReachyTTS(text: string, wobble = true): Promise<{ ok: boolean; message: string; tts_binary?: string }> {
  return reachyJson<{ ok: boolean; message: string; tts_binary?: string }>(
    '/api/reachy/chat/speak',
    { method: 'POST', body: JSON.stringify({ text, wobble }) },
  )
}

export function stopReachyChat(): Promise<{ ok: boolean; state: string }> {
  return reachyJson<{ ok: boolean; state: string }>('/api/reachy/chat/stop', { method: 'POST' })
}

export function getReachyChatTtsAvailability(): Promise<ReachyChatTtsAvailability> {
  return reachyJson<ReachyChatTtsAvailability>('/api/reachy/chat/tts/availability')
}

// M26: Conversation provider routing (botversex vs Pro)
export interface ReachyConversationProviderInfo {
  label: string
  description: string
  requires_key: boolean
  is_pro: boolean
  key_env?: string
  key_hint?: string
}

export interface ReachyConversationEnvTemplateV2 {
  providers: Record<ReachyConversationProvider, ReachyConversationProviderInfo>
  default_provider: ReachyConversationProvider
  backends: Record<string, {
    label: string
    requires_key: boolean
    key_env?: string
    default_model?: string | null
    key_hint?: string
    env?: Record<string, string>
  }>
  cli_flags: Record<string, unknown>
  app_info: { name: string; hf_url: string; hf_id: string; description: string }
}

export interface ReachyConversationStatusV2 {
  running: boolean
  state: string
  provider: ReachyConversationProvider | null
  backend?: ReachyConversationBackend | null
  model?: string | null
  head_tracker?: ReachyHeadTracker | null
  local_vision: boolean
  gradio: boolean
  no_camera: boolean
  pid?: number | null
  started_at?: number | null
  returncode?: number | null
  error?: string | null
  command?: string[] | null
  gradio_url?: string | null
  realtime_backend_available: boolean
  pro_backend_installed: boolean
  log_tail: string[]
}

export function getReachyConversationEnvTemplateV2(): Promise<ReachyConversationEnvTemplateV2> {
  return reachyJson<ReachyConversationEnvTemplateV2>('/api/reachy/conversation/env-template')
}

export function getReachyConversationStatusV2(): Promise<ReachyConversationStatusV2> {
  return reachyJson<ReachyConversationStatusV2>('/api/reachy/conversation/status')
}

export function startReachyConversationV2(
  req: {
    provider?: ReachyConversationProvider
    backend?: ReachyConversationBackend
    api_key?: string | null
    model?: string | null
    hf_token?: string | null
    head_tracker?: ReachyHeadTracker | null
    gradio?: boolean
    no_camera?: boolean
    local_vision?: boolean
    auto_install?: boolean
    audio_input_id?: string | null
    audio_input_match?: string | null
  },
): Promise<{
  ok: boolean
  provider?: string
  message: string
  stage?: string
  gradio_url?: string | null
  pid?: number
  backend?: string
  mic_prep?: Record<string, unknown>
}> {
  return reachyJson('/api/reachy/conversation/start', {
    method: 'POST',
    body: JSON.stringify({ provider: 'official', gradio: true, no_camera: true, ...req }),
    timeoutMs: CONVERSATION_START_TIMEOUT_MS,
  })
}

export interface ReachyAudioInputSource {
  id: string
  name: string
  default?: boolean
}

export function listReachyAudioInputs(): Promise<{
  ok: boolean
  sources: ReachyAudioInputSource[]
  default_id?: string | null
}> {
  return reachyJson('/api/reachy/conversation/audio-inputs')
}

export function setReachyAudioInput(id: string): Promise<{
  ok: boolean
  id: string
  name?: string | null
  match?: string | null
  hint?: string
}> {
  return reachyJson('/api/reachy/conversation/audio-input', {
    method: 'POST',
    body: JSON.stringify({ id }),
  })
}

export interface ReachyAudioLevel {
  ok: boolean
  id?: string | null
  rms: number
  peak: number
  db: number
  samples?: number
  reason?: string
  error?: string
}

/** Short PipeWire mic sample for the loudness meter (rms/peak 0..1). */
export function getReachyAudioLevel(
  id?: string | null,
  durationMs = 80,
): Promise<ReachyAudioLevel> {
  const qs = new URLSearchParams()
  if (id) qs.set('id', id)
  qs.set('duration_ms', String(durationMs))
  return reachyJson(`/api/reachy/conversation/audio-level?${qs.toString()}`, {
    timeoutMs: 2500,
  })
}

// Seeed Studio 豆包本体对话（机器人麦克风 + 喇叭，见 wiki.seeedstudio.com）
export interface ReachySeeedConversationStatus {
  installed: boolean
  running: boolean
  state: string
  pid?: number | null
  log_tail: string[]
  audio_hint?: string | null
  wiki_url?: string
  keys_file?: string
  keys_configured?: boolean
  daemon_audio_deactivated?: boolean
}

export function getReachySeeedConversationStatus(): Promise<ReachySeeedConversationStatus> {
  return reachyJson<ReachySeeedConversationStatus>('/api/reachy/seeed-conversation/status')
}

export function installReachySeeedConversation(force = false): Promise<{ ok: boolean; message: string }> {
  return reachyJson('/api/reachy/seeed-conversation/install', {
    method: 'POST',
    body: JSON.stringify({ force }),
  })
}

export function setupReachySeeedConversation(opts?: {
  restart_daemon?: boolean
  install?: boolean
  set_volume?: boolean
}): Promise<{
  ok: boolean
  message: string
  keys_file?: string
  keys_configured?: boolean
  steps?: unknown[]
}> {
  return reachyJson('/api/reachy/seeed-conversation/setup', {
    method: 'POST',
    body: JSON.stringify({
      restart_daemon: opts?.restart_daemon ?? true,
      install: opts?.install ?? true,
      set_volume: opts?.set_volume ?? true,
    }),
  })
}

export function startReachySeeedConversation(req: {
  llm_api_key?: string
  asr_api_key?: string
  model?: string
  auto_install?: boolean
  save_keys?: boolean
}): Promise<{ ok: boolean; message: string; pid?: number }> {
  return reachyJson('/api/reachy/seeed-conversation/start', {
    method: 'POST',
    body: JSON.stringify(req),
    timeoutMs: CONVERSATION_START_TIMEOUT_MS,
  })
}

export function stopReachySeeedConversation(): Promise<{ ok: boolean; message: string }> {
  return reachyJson('/api/reachy/seeed-conversation/stop', { method: 'POST' })
}

