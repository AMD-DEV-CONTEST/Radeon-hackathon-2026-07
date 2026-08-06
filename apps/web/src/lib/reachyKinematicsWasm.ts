/**
 * Reachy Mini Stewart passive-joint solver (official Pollen WASM, ~30 KB).
 *
 * When the daemon runs AnalyticalKinematics (default USB mode) it streams
 * head_joints + head_pose but passive_joints === null. The official
 * reachy-mini-desktop-app calculates the 21 passive values locally with this
 * same WASM module — we do the same instead of hiding rods + RPY override.
 *
 * Source: pollen-robotics/reachy-mini-desktop-app/kinematics-wasm
 */

import type { ReachyFullState } from './reachyApi'
import {
  extractHeadRpyFromPose,
  headRpyToNamedJoints,
  mergePassiveJoints,
  namedJointsToUrdf,
  hasPassiveJoints,
} from './reachyVirtualPreview'

type WasmModule = {
  default: (url?: string | URL) => Promise<unknown>
  calculate_passive_joints: (headJoints: Float64Array, headPose: Float64Array) => Float64Array
}

let wasmModule: WasmModule | null = null
let wasmLoading: Promise<WasmModule | null> | null = null

/** Lazy-load the WASM singleton (browser only). */
export async function loadReachyKinematicsWasm(): Promise<WasmModule | null> {
  if (wasmModule) return wasmModule
  if (wasmLoading) return wasmLoading

  wasmLoading = (async () => {
    try {
      const wasm = (await import('./reachy-kinematics/reachy_mini_kinematics_wasm.js')) as WasmModule
      await wasm.default(new URL('./reachy-kinematics/reachy_mini_kinematics_wasm_bg.wasm', import.meta.url))
      wasmModule = wasm
      return wasm
    } catch (err) {
      console.warn('[ReachyKinematicsWasm] load failed — will use visual fallback', err)
      return null
    }
  })()

  return wasmLoading
}

/** Flatten head_pose (4×4 row-major, dict RPY, or nested arrays) to 16 floats. */
export function headPoseToMatrix16(pose: ReachyFullState['head_pose']): Float64Array | null {
  if (!pose) return null

  if (Array.isArray(pose) && pose.length === 4 && Array.isArray(pose[0])) {
    const out = new Float64Array(16)
    let i = 0
    for (let r = 0; r < 4; r++) {
      const row = pose[r] as number[]
      for (let c = 0; c < 4; c++) {
        out[i++] = Number(row[c] ?? 0)
      }
    }
    return out
  }

  if (Array.isArray(pose) && pose.length === 16) {
    return new Float64Array(pose.map((v) => Number(v)))
  }

  if (typeof pose === 'object' && !Array.isArray(pose)) {
    const roll = typeof pose.roll === 'number' ? pose.roll : 0
    const pitch = typeof pose.pitch === 'number' ? pose.pitch : 0
    const yaw = typeof pose.yaw === 'number' ? pose.yaw : 0
    const cr = Math.cos(roll)
    const sr = Math.sin(roll)
    const cp = Math.cos(pitch)
    const sp = Math.sin(pitch)
    const cy = Math.cos(yaw)
    const sy = Math.sin(yaw)
    // ZYX intrinsic → row-major 4×4
    return new Float64Array([
      cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr, 0,
      sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr, 0,
      -sp, cp * sr, cp * cr, 0,
      0, 0, 0, 1,
    ])
  }

  return null
}

/** Build [yaw_body, stewart_1..6] from daemon state. */
export function headJointsFromState(state: ReachyFullState | null | undefined): Float64Array | null {
  if (!state) return null
  const raw = state.head_joints ?? state.target_head_joints
  if (!Array.isArray(raw) || raw.length < 7) {
    const bodyYaw = typeof state.body_yaw === 'number' ? state.body_yaw : 0
    return new Float64Array([bodyYaw, 0, 0, 0, 0, 0, 0])
  }
  return new Float64Array(raw.slice(0, 7).map((v) => Number(v)))
}

/**
 * Stewart motor angles for URDF / WASM that match the measured head_pose.
 *
 * The daemon's raw head_joints are motor encoder values for the closed Stewart
 * loop; URDF is an open tree and cannot consume them directly. When head_pose
 * is available we derive the 6 Stewart URDF joints from its RPY (same mapping
 * as virtual mode and the motion editor) so rods + head stay connected.
 */
export function poseAlignedNamedJoints(
  state: ReachyFullState | null | undefined,
): Record<string, number> | null {
  if (!state?.head_pose) return null
  const rpy = extractHeadRpyFromPose(state.head_pose)
  const bodyYaw =
    typeof state.body_yaw === 'number'
      ? state.body_yaw
      : typeof state.head_joints?.[0] === 'number'
        ? state.head_joints[0]
        : 0
  return headRpyToNamedJoints(rpy.roll, rpy.pitch, rpy.yaw, bodyYaw)
}

export function poseAlignedHeadJoints(state: ReachyFullState | null | undefined): Float64Array | null {
  const named = poseAlignedNamedJoints(state)
  if (!named) return null
  return new Float64Array([
    named.body_rotation,
    named.stewart_1,
    named.stewart_2,
    named.stewart_3,
    named.stewart_4,
    named.stewart_5,
    named.stewart_6,
  ])
}

/**
 * Compute 21 passive joint angles locally (daemon Placo not required).
 * Returns null if WASM not ready or inputs invalid.
 */
export function calculatePassiveJointsSync(
  state: ReachyFullState | null | undefined,
): number[] | null {
  if (!wasmModule || !state) return null

  const headJoints = headJointsFromState(state)
  const headPose = headPoseToMatrix16(state.head_pose ?? state.target_head_pose)
  if (!headJoints || !headPose) return null

  try {
    const result = wasmModule.calculate_passive_joints(headJoints, headPose)
    return Array.from(result)
  } catch (err) {
    console.warn('[ReachyKinematicsWasm] calculate_passive_joints failed', err)
    return null
  }
}

/** Identity 4×4 head pose (row-major lists) for neutral WASM solve. */
export const REACHY_NEUTRAL_HEAD_MATRIX: number[][] = [
  [1, 0, 0, 0],
  [0, 1, 0, 0],
  [0, 0, 1, 0],
  [0, 0, 0, 1],
]

/** Neutral daemon state: all motors at zero, head upright. */
export function reachyNeutralState(): import('./reachyApi').ReachyFullState {
  return {
    head_pose: REACHY_NEUTRAL_HEAD_MATRIX,
    head_joints: [0, 0, 0, 0, 0, 0, 0],
    body_yaw: 0,
    antennas_position: [0, 0],
  }
}

/**
 * URDF joint map for neutral rest pose (WASM passive joints + zero motors).
 * Used before the first WS frame arrives so the model is not shown tilted.
 */
export function buildNeutralUrdfJoints(): Record<string, number> {
  const named: Record<string, number> = {
    body_rotation: 0,
    stewart_1: 0,
    stewart_2: 0,
    stewart_3: 0,
    stewart_4: 0,
    stewart_5: 0,
    stewart_6: 0,
    right_antenna: 0,
    left_antenna: 0,
  }
  const passive = calculatePassiveJointsSync(reachyNeutralState())
  return namedJointsToUrdf(mergePassiveJoints(named, passive))
}

/**
 * Ensure URDF joint map includes 21 passive joints. Uses daemon passive_joints
 * when present; otherwise WASM (same as official desktop app). Falls back to
 * precomputed neutralUrdf when WASM is not loaded yet.
 */
export function ensureReachyUrdfJoints(
  named: Record<string, number>,
  state: ReachyFullState | null | undefined,
  neutralUrdf: Record<string, number>,
): Record<string, number> {
  const mergedNamed = { ...named }
  if (!hasPassiveJoints(mergedNamed)) {
    const passiveFromDaemon = state?.passive_joints
    if (Array.isArray(passiveFromDaemon) && passiveFromDaemon.length > 0) {
      Object.assign(mergedNamed, mergePassiveJoints(mergedNamed, passiveFromDaemon))
    } else {
      const wasmState: ReachyFullState = state ?? {
        head_joints: [
          mergedNamed.body_rotation ?? 0,
          mergedNamed.stewart_1 ?? 0,
          mergedNamed.stewart_2 ?? 0,
          mergedNamed.stewart_3 ?? 0,
          mergedNamed.stewart_4 ?? 0,
          mergedNamed.stewart_5 ?? 0,
          mergedNamed.stewart_6 ?? 0,
        ],
        head_pose: state?.head_pose ?? REACHY_NEUTRAL_HEAD_MATRIX,
        body_yaw: mergedNamed.body_rotation ?? 0,
      }
      const passive = calculatePassiveJointsSync(wasmState)
      if (passive) {
        Object.assign(mergedNamed, mergePassiveJoints({}, passive))
      }
    }
  }

  const urdf = namedJointsToUrdf(mergedNamed)
  if (hasPassiveJoints(urdf)) return urdf
  if (Object.keys(neutralUrdf).length > 0) return neutralUrdf
  return urdf
}
