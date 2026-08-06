/**
 * BotClaw v0.1 最小 TS 类型 (apps/web 端内嵌).
 *
 * NOTE: 理想做法是从 `@botversex/botclaw-spec` workspace 包导入,
 *   目前为避免跨包构建复杂度, 在 web 端复制一份最小子集.
 *   字段必须严格对齐 packages/botclaw-spec/ts/index.ts.
 */

export const BOTCLAW_SPEC_VERSION = '0.4.0'

export type JointName = '1' | '2' | '3' | '4' | '5' | '6'

export type JointMap = Record<JointName, number>

export interface JointUpdateMeta {
  fps?: number
  source?: string
  [k: string]: unknown
}

export interface JointUpdate {
  type: 'joint_update'
  robot_id: string
  timestamp: number
  joints: JointMap
  servo_values?: Record<string, number>
  meta?: JointUpdateMeta
}

export function isJointUpdate(x: unknown): x is JointUpdate {
  if (!x || typeof x !== 'object') return false
  const m = x as Record<string, unknown>
  if (m.type !== 'joint_update') return false
  if (typeof m.robot_id !== 'string') return false
  if (typeof m.timestamp !== 'number') return false
  const j = m.joints as Record<string, unknown> | undefined
  if (!j || typeof j !== 'object') return false
  // Accept any payload with at least one numeric joint so that runtimes with
  // non-SO-101 joint layouts (e.g. Reachy Mini's 9 DoF) still flow through.
  // SO-101 consumers should defensively default missing keys to 0.
  return Object.values(j).some((v) => typeof v === 'number')
}

export const JOINT_NAMES: JointName[] = ['1', '2', '3', '4', '5', '6']

// ---------- RobotState (v0.4) ----------

export interface JointLimit {
  lo: number
  hi: number
}

export interface RobotSafety {
  estop: boolean
  clamped?: string[]
  max_delta_rad?: number
  [k: string]: unknown
}

export interface RobotState {
  type: 'robot_state'
  robot_id: string
  timestamp: number
  joints?: Partial<Record<JointName, number | null>>
  servo_values?: Partial<Record<JointName, number | null>>
  teleop_connected: boolean
  ui_clients: number
  is_recording: boolean
  buffer_size?: number
  temperatures_c?: Partial<Record<JointName, number | null>>
  currents_a?: Partial<Record<JointName, number | null>>
  voltages_v?: Partial<Record<JointName, number | null>>
  limits_rad?: Partial<Record<JointName, JointLimit>>
  safety?: RobotSafety
  fps_observed?: number
  [k: string]: unknown
}

export function isRobotState(x: unknown): x is RobotState {
  if (!x || typeof x !== 'object') return false
  const m = x as Record<string, unknown>
  return m.type === 'robot_state' && typeof m.robot_id === 'string'
}
