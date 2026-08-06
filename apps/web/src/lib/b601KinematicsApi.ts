import { agentFetch } from './localAgent'

export interface KinematicsHealth {
  ready: boolean
  pinocchio: boolean
  sdk: boolean
  urdf_exists: boolean
  sdk_path: string | null
  install_script: string
  ready_pose?: {
    joints: Record<string, number>
    position: number[]
    orientation: number[]
    orientation_deg?: number[]
  }
}

export interface ReadyPoseResponse {
  ok: boolean
  joints: Record<string, number>
  position: number[]
  orientation: number[]
  orientation_deg?: number[]
}

export interface EePose {
  position: number[]
  rotation_matrix: number[][]
  euler: number[]
  euler_deg: number[]
}

export interface EePoseResponse {
  ok: boolean
  joints: Record<string, number>
  pose: EePose | null
  message?: string
  timestamp?: number
}

export async function getB601KinematicsReadyPose(): Promise<ReadyPoseResponse> {
  const r = await agentFetch('/api/b601/kinematics/ready_pose')
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export async function getB601KinematicsHealth(): Promise<KinematicsHealth> {
  const r = await agentFetch('/api/b601/kinematics/health')
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export async function b601KinematicsFk(joints: Record<string, number>) {
  const r = await agentFetch('/api/b601/kinematics/fk', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ joints }),
  })
  if (!r.ok) throw new Error(await r.text())
  return r.json() as Promise<{ ok: boolean; pose: EePose }>
}

export async function b601KinematicsIk(
  position: number[],
  orientation?: number[],
  q_seed?: Record<string, number>,
) {
  const r = await agentFetch('/api/b601/kinematics/ik', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ position, orientation, q_seed }),
  })
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export async function b601KinematicsEePose(): Promise<EePoseResponse> {
  const r = await agentFetch('/api/b601/kinematics/ee_pose')
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export async function b601KinematicsMovePose(opts: {
  position: number[]
  orientation?: number[]
  q_seed?: Record<string, number>
  duration?: number
  dry_run?: boolean
}) {
  const r = await agentFetch('/api/b601/kinematics/move_pose', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      duration: 2.0,
      dry_run: true,
      ...opts,
    }),
  })
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export async function b601KinematicsMoveJoints(opts: {
  joints: Record<string, number>
  duration?: number
  dry_run?: boolean
}) {
  const r = await agentFetch('/api/b601/kinematics/move_joints', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ duration: 2.0, dry_run: true, ...opts }),
  })
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export async function b601KinematicsStop() {
  const r = await agentFetch('/api/b601/kinematics/stop', { method: 'POST' })
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export function b601KinematicsEePoseWsUrl(): string {
  const base = typeof window !== 'undefined' ? window.location : null
  const proto = base?.protocol === 'https:' ? 'wss:' : 'ws:'
  const host = base?.host ?? 'localhost:5173'
  return `${proto}//${host}/api/b601/kinematics/ws/ee_pose`
}
