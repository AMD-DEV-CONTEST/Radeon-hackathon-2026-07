import { agentFetch } from './localAgent'

export interface Ros2Health {
  ready: boolean
  ros2: boolean
  ros_distro: string
  workspace: string
  workspace_exists: boolean
  bringup_running?: boolean
  install_script: string
}

export async function getB601Ros2Health(): Promise<Ros2Health> {
  const r = await agentFetch('/api/b601/ros2/health')
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export async function b601Ros2Launch(opts?: { use_rviz?: boolean; channel?: string }) {
  const r = await agentFetch('/api/b601/ros2/launch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ use_rviz: false, channel: 'can0', ...opts }),
  })
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export async function b601Ros2Stop() {
  const r = await agentFetch('/api/b601/ros2/stop', { method: 'POST' })
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export async function b601Ros2Status() {
  const r = await agentFetch('/api/b601/ros2/status')
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export async function b601Ros2MovePose(opts: {
  position: number[]
  orientation?: number[]
  duration?: number
}) {
  const r = await agentFetch('/api/b601/ros2/move_pose', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      orientation: [0, 0, 0, 1],
      duration: 2.0,
      ...opts,
    }),
  })
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export async function b601Ros2GripperOpen() {
  const r = await agentFetch('/api/b601/ros2/gripper/open', { method: 'POST' })
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export async function b601Ros2GripperClose() {
  const r = await agentFetch('/api/b601/ros2/gripper/close', { method: 'POST' })
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export async function b601Ros2GravityCompStart() {
  const r = await agentFetch('/api/b601/ros2/gravity_comp/start', { method: 'POST' })
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export async function b601Ros2GravityCompStop() {
  const r = await agentFetch('/api/b601/ros2/gravity_comp/stop', { method: 'POST' })
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export async function b601GravityCompStart(opts: {
  mode: 'basic' | 'lock'
  joint_gains?: Record<number, number>
}) {
  const r = await agentFetch('/api/b601/gravity_comp/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      joint_gains: opts.joint_gains ?? {},
      ...opts,
    }),
  })
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export async function b601GravityCompStop() {
  const r = await agentFetch('/api/b601/gravity_comp/stop', { method: 'POST' })
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

export async function b601GravityCompStatus() {
  const r = await agentFetch('/api/b601/gravity_comp/status')
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}
