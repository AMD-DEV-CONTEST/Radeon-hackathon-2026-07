import { agentFetch } from './localAgent'

export interface LeKiwiHealth {
  ok: boolean
  deployment_mode: 'remote' | 'wired'
  remote_ip: string
  command_port: number
  observation_port: number
  command_reachable: boolean
  observations_reachable: boolean
  remote_host_ready: boolean
  robot_port: string
  wired_port_present: boolean
  leader_port: string
  leader_present: boolean
  lerobot_teleoperate: boolean
  lerobot_record: boolean
  motor_bus: string
  teleop_running: boolean
  record_running: boolean
  issues: string[]
}

export interface LeKiwiSessionStatus {
  running: boolean
  starting?: boolean
  session_id?: string | null
  pid?: number | null
  started_at?: number | null
  uptime_s?: number | null
  repo_id?: string | null
  episode_current?: number | null
  episode_total?: number | null
  log_tail: string[]
  last_error?: string | null
}

async function lekiwiJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await agentFetch(`/api/lekiwi${path}`, {
    ...init,
    headers: {
      ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
      ...init?.headers,
    },
  })
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`
    try {
      const body = await response.json()
      detail = body?.detail ?? body?.message ?? detail
    } catch {
      // Preserve HTTP fallback.
    }
    throw new Error(String(detail))
  }
  return response.json() as Promise<T>
}

export function getLeKiwiHealth(): Promise<LeKiwiHealth> {
  return lekiwiJson('/health')
}

export function getLeKiwiTeleopStatus(): Promise<LeKiwiSessionStatus> {
  return lekiwiJson('/teleop/status')
}

export function getLeKiwiRecordStatus(): Promise<LeKiwiSessionStatus> {
  return lekiwiJson('/record/status')
}

export function startLeKiwiTeleop(input: {
  remoteIp: string
  leaderPort: string
}): Promise<{ ok: boolean; session_id: string; message: string }> {
  return lekiwiJson('/teleop/start', {
    method: 'POST',
    body: JSON.stringify({
      deployment_mode: 'remote',
      remote_ip: input.remoteIp,
      leader_port: input.leaderPort,
    }),
  })
}

export function stopLeKiwiTeleop(): Promise<{ ok: boolean; message?: string }> {
  return lekiwiJson('/teleop/stop', { method: 'POST' })
}

export function startLeKiwiRecord(input: {
  remoteIp: string
  leaderPort: string
  repoId: string
  task: string
  episodes: number
}): Promise<{ ok: boolean; session_id: string; message: string }> {
  return lekiwiJson('/record/start', {
    method: 'POST',
    body: JSON.stringify({
      deployment_mode: 'remote',
      remote_ip: input.remoteIp,
      leader_port: input.leaderPort,
      repo_id: input.repoId,
      single_task: input.task,
      num_episodes: input.episodes,
    }),
  })
}

export function stopLeKiwiRecord(): Promise<{ ok: boolean }> {
  return lekiwiJson('/record/stop', { method: 'POST' })
}

export function emergencyStopLeKiwi(): Promise<{
  ok: boolean
  base_stop: string
  torque_disabled: boolean
  message: string
}> {
  return lekiwiJson('/disable', { method: 'POST' })
}
