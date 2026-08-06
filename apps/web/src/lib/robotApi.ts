import { agentFetch } from './localAgent'
import { friendlyRobotListError } from './friendlyErrors'

export interface RobotManifest {
  runtime_id: string
  robot_type: string
  display_name: string
  /** If true, this robot is in preview — UI shows a "Preview" badge and may hide some flows. */
  preview?: boolean
  /** If true, this robot is hidden from the /robots catalog (e.g. variant siblings). */
  hidden_from_catalog?: boolean
  joint_count?: number
  joint_names?: string[]
  urdf_url?: string | null
  transport?: {
    kind: string
    ports?: Record<string, string>
    [key: string]: unknown
  }
  service?: {
    kind: string
    host?: string
    port?: number
    sdk_path?: string
    log_file?: string
    [key: string]: unknown
  }
  capabilities?: Record<string, boolean>
  dependencies?: {
    policy?: string
    python_modules?: string[]
    binaries?: string[]
    install_hint?: string
  }
  ui?: {
    route?: string
  }
  [key: string]: unknown
}

export interface RobotsResponse {
  schema_version: string
  robots: RobotManifest[]
}

export interface RobotDependencyCheck {
  kind: 'python_module' | 'binary' | string
  name: string
  ok: boolean
}

export interface RobotDependenciesResponse {
  runtime_id: string
  policy: string
  python: string
  checks: RobotDependencyCheck[]
  ok: boolean
  install_hint?: string | null
}

export interface RobotProvisionResponse {
  ok: boolean
  runtime_id?: string
  policy: string
  message?: string
  venv?: string
  python?: string
  steps?: Array<{
    command: string[]
    returncode: number
    ok: boolean
    output: string
  }>
}

async function robotJson<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await agentFetch(path, {
      ...init,
      headers: {
        ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
        ...init?.headers,
      },
    })
  } catch (e) {
    if (e instanceof DOMException && e.name === 'TimeoutError') {
      throw new Error(friendlyRobotListError('实时服务未响应（超时）'))
    }
    if (e instanceof TypeError) {
      throw new Error(friendlyRobotListError('无法连接实时服务'))
    }
    throw e
  }

  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`
    try {
      const body = await response.json()
      detail = body?.detail?.message ?? body?.detail ?? body?.message ?? detail
    } catch {
      // Keep HTTP fallback.
    }
    throw new Error(String(detail))
  }

  return response.json() as Promise<T>
}

let robotsListCache: { at: number; body: RobotsResponse } | null = null
const ROBOTS_LIST_TTL_MS = 60_000

export interface RuntimeEntry {
  runtime_id: string
  robot_type: string
  display_name: string
  joint_count?: number
  urdf_url?: string
}

let runtimesListCache: { at: number; body: { runtimes: RuntimeEntry[] } } | null = null

export function listRuntimes(force = false): Promise<{ runtimes: RuntimeEntry[] }> {
  const now = Date.now()
  if (!force && runtimesListCache && now - runtimesListCache.at < ROBOTS_LIST_TTL_MS) {
    return Promise.resolve(runtimesListCache.body)
  }
  return agentFetch('/api/runtimes')
    .then((r) => {
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
      return r.json() as Promise<{ runtimes: RuntimeEntry[] }>
    })
    .then((body) => {
      runtimesListCache = { at: now, body }
      return body
    })
    .catch((e) => {
      if (e instanceof DOMException && e.name === 'TimeoutError') {
        throw new Error(friendlyRobotListError('实时服务未响应（超时）'))
      }
      throw e
    })
}

export function listRobotManifests(force = false): Promise<RobotsResponse> {
  const now = Date.now()
  if (!force && robotsListCache && now - robotsListCache.at < ROBOTS_LIST_TTL_MS) {
    return Promise.resolve(robotsListCache.body)
  }
  return robotJson<RobotsResponse>('/api/robots').then((body) => {
    robotsListCache = { at: now, body }
    return body
  })
}

export function getRobotManifest(runtimeId: string): Promise<RobotManifest> {
  return robotJson<RobotManifest>(`/api/robots/${encodeURIComponent(runtimeId)}`)
}

export function getRobotStatus<T = unknown>(runtimeId: string): Promise<T> {
  return robotJson<T>(`/api/robots/${encodeURIComponent(runtimeId)}/status`)
}

export function startRobotService<T = unknown>(runtimeId: string): Promise<T> {
  return robotJson<T>(`/api/robots/${encodeURIComponent(runtimeId)}/service/start`, {
    method: 'POST',
  })
}

export function stopRobotService<T = unknown>(runtimeId: string): Promise<T> {
  return robotJson<T>(`/api/robots/${encodeURIComponent(runtimeId)}/service/stop`, {
    method: 'POST',
  })
}

export function getRobotDependencies(runtimeId: string): Promise<RobotDependenciesResponse> {
  return robotJson<RobotDependenciesResponse>(
    `/api/robots/${encodeURIComponent(runtimeId)}/dependencies`,
  )
}

export function provisionRobotDependencies(runtimeId: string): Promise<RobotProvisionResponse> {
  return robotJson<RobotProvisionResponse>(
    `/api/robots/${encodeURIComponent(runtimeId)}/dependencies/provision`,
    { method: 'POST' },
  )
}

export interface RobotStatePayload {
  type: string
  runtime_id: string
  robot_id?: string
  timestamp: number
  connected?: boolean
  teleop_running?: boolean
  joints?: Record<string, number>
  health?: Record<string, unknown>
  [key: string]: unknown
}

export function getRobotState(runtimeId: string): Promise<RobotStatePayload> {
  return robotJson<RobotStatePayload>(`/api/robots/${encodeURIComponent(runtimeId)}/state`)
}
