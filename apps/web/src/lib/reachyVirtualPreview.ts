import type { ReachyFullState, ReachyRecordFrame } from './reachyApi'
import type { ReachyPoseFrame } from './reachyMotionClip'
import * as THREE from 'three'
import { updateRobotJoints } from './urdf'

/** Head pose from daemon: RPY dict or 4×4 matrix. */
export function extractHeadRpyFromPose(
  pose: ReachyFullState['head_pose'],
): { roll: number; pitch: number; yaw: number } {
  if (pose && !Array.isArray(pose) && typeof pose === 'object') {
    return {
      roll: typeof pose.roll === 'number' && Number.isFinite(pose.roll) ? pose.roll : 0,
      pitch: typeof pose.pitch === 'number' && Number.isFinite(pose.pitch) ? pose.pitch : 0,
      yaw: typeof pose.yaw === 'number' && Number.isFinite(pose.yaw) ? pose.yaw : 0,
    }
  }
  if (Array.isArray(pose) && pose.length === 4 && Array.isArray(pose[1])) {
    try {
      const row1 = pose[1] as number[]
      const row2 = pose[2] as number[]
      const r10 = Number(row1[0])
      const r11 = Number(row1[1])
      const r20 = Number(row2[0])
      const r21 = Number(row2[1])
      const r22 = Number(row2[2])
      const pitch = Math.asin(Math.max(-1, Math.min(1, -r20)))
      const roll = Math.atan2(r21, r22)
      const yaw = Math.atan2(r10, Math.abs(r11) > 1e-6 ? r11 : 1)
      return { roll, pitch, yaw }
    } catch {
      /* fall through */
    }
  }
  return { roll: 0, pitch: 0, yaw: 0 }
}

/** Approximate Reachy Stewart joints from head RPY (matches virtual backend preview). */
export function headRpyToNamedJoints(
  roll: number,
  pitch: number,
  yaw: number,
  bodyYaw: number,
): Record<string, number> {
  return {
    body_rotation: bodyYaw,
    stewart_1: roll * 0.45,
    stewart_2: pitch * 0.55,
    stewart_3: -pitch * 0.55,
    stewart_4: roll * 0.35,
    stewart_5: yaw * 0.25,
    stewart_6: -yaw * 0.25,
    right_antenna: 0,
    left_antenna: 0,
  }
}

export function namedJointsToUrdf(named: Record<string, number>): Record<string, number> {
  const out: Record<string, number> = {}
  for (const [name, value] of Object.entries(named)) {
    const urdfName = name === 'body_rotation' ? 'yaw_body' : name
    out[urdfName] = value
  }
  return out
}

/** Map a daemon move / record frame to URDF joint angles for the 3D twin. */
export function reachyRecordFrameToUrdfJoints(frame: ReachyRecordFrame): Record<string, number> {
  const headRpy = extractHeadRpyFromPose(frame.head)
  const bodyYaw = typeof frame.body_yaw === 'number' ? frame.body_yaw : 0
  const out = namedJointsToUrdf(
    headRpyToNamedJoints(headRpy.roll, headRpy.pitch, headRpy.yaw, bodyYaw),
  )
  const antennas = frame.antennas ?? [0, 0]
  out.right_antenna = antennas[0] ?? 0
  out.left_antenna = antennas[1] ?? 0
  return out
}

/**
 * Editor uses the SAME kinematic preview as the live RobotReachyMini view:
 * head RPY drives the 6 Stewart legs (approximation), body_yaw + antennas drive their
 * joints. Nothing is hidden or reparented, so the whole model stays connected.
 * Export / real robot still use the exact daemon head RPY.
 */
export function applyReachyEditorDisplayPose(
  robot: THREE.Object3D,
  pose: ReachyPoseFrame,
): void {
  const named = headRpyToNamedJoints(
    pose.head.roll,
    pose.head.pitch,
    pose.head.yaw,
    pose.bodyYaw,
  )
  const out = namedJointsToUrdf(named)
  out.left_antenna = pose.antennas[0]
  out.right_antenna = pose.antennas[1]
  updateRobotJoints(robot, out)
  // The URDF stewart chain only really drives head yaw (via stewart_6); pitch
  // and roll get lost because URDF can't close the loop. Override the head
  // link's world rotation directly so it tracks the commanded RPY 1:1.
  applyReachyHeadWorldRpy(robot, pose.head.roll, pose.head.pitch, pose.head.yaw)
}

// Scratch quaternions / euler — reused across calls to avoid GC churn.
const _bodyWorldQuat = new THREE.Quaternion()
const _headDesiredWorldQuat = new THREE.Quaternion()
const _parentWorldQuat = new THREE.Quaternion()
const _invParentQuat = new THREE.Quaternion()
const _deltaEuler = new THREE.Euler()
const _deltaQuat = new THREE.Quaternion()

/**
 * Override the Reachy Mini head link's world rotation so it equals
 *   body_world_quaternion * RPY(roll, pitch, yaw)
 *
 * This bypasses the broken Stewart kinematic chain in the URDF (URDF can't
 * represent closed loops, so only one of the 6 rods actually drives the head
 * and pitch/roll get lost). Instead, we set `link_xl_330.quaternion` to the
 * local rotation that produces the desired world rotation given the head's
 * parent world transform.
 *
 * Call AFTER `updateRobotJoints` so the body's `yaw_body` joint has already
 * been applied. Position is left to the kinematic chain (the head sits at a
 * roughly fixed offset from the body; small platform translations are
 * negligible for visualisation).
 */
export function applyReachyHeadWorldRpy(
  robot: THREE.Object3D,
  roll: number,
  pitch: number,
  yaw: number,
): void {
  const head = getReachyHeadLink(robot)
  const body = getReachyBodyLink(robot)
  if (!head || !body || !head.parent) return

  // Recompute world matrices so the parent's world quaternion reflects the
  // latest joint angles (yaw_body in particular).
  robot.updateWorldMatrix(true, true)

  body.getWorldQuaternion(_bodyWorldQuat)

  // RPY convention: roll about X, pitch about Y, yaw about Z, intrinsic ZYX
  // order (matches the HeadGizmo below and the daemon's convention).
  _deltaEuler.set(roll, pitch, yaw, 'ZYX')
  _deltaQuat.setFromEuler(_deltaEuler)
  _headDesiredWorldQuat.copy(_bodyWorldQuat).multiply(_deltaQuat)

  head.parent.getWorldQuaternion(_parentWorldQuat)
  _invParentQuat.copy(_parentWorldQuat).invert()
  head.quaternion.copy(_invParentQuat).multiply(_headDesiredWorldQuat)
  head.updateMatrix()
}

/**
 * Create a head-pose updater that treats the URDF's zero pose as canonical.
 *
 * The exported Reachy Mini URDF already has the correct nominal head
 * orientation. `applyReachyHeadWorldRpy(..., 0, 0, 0)` does NOT preserve that
 * orientation: it replaces it with the body's world quaternion, which is why
 * the head appeared permanently tilted on the catalog hero.
 *
 * This closure captures the neutral body→head quaternion from the untouched
 * URDF on its first call, then composes action RPY as a delta:
 *
 *   desiredHeadWorld = bodyWorld * neutralBodyToHead * actionDelta
 *
 * Position is never changed. Stewart/passive joints must remain at their URDF
 * zero values when using this fallback (no Placo closed-loop solution).
 */
export function createReachyHeadDeltaUpdater(): (
  robot: THREE.Object3D,
  roll: number,
  pitch: number,
  yaw: number,
) => void {
  const neutralBodyToHead = new THREE.Quaternion()
  const bodyWorld = new THREE.Quaternion()
  const headWorld = new THREE.Quaternion()
  const parentWorld = new THREE.Quaternion()
  const invBodyWorld = new THREE.Quaternion()
  const invParentWorld = new THREE.Quaternion()
  const desiredWorld = new THREE.Quaternion()
  const deltaEuler = new THREE.Euler()
  const deltaQuat = new THREE.Quaternion()
  let captured = false

  return (robot, roll, pitch, yaw) => {
    const head = getReachyHeadLink(robot)
    const body = getReachyBodyLink(robot)
    if (!head || !body || !head.parent) return

    robot.updateWorldMatrix(true, true)
    body.getWorldQuaternion(bodyWorld)

    if (!captured) {
      head.getWorldQuaternion(headWorld)
      invBodyWorld.copy(bodyWorld).invert()
      neutralBodyToHead.copy(invBodyWorld).multiply(headWorld)
      captured = true
    }

    deltaEuler.set(roll, pitch, yaw, 'ZYX')
    deltaQuat.setFromEuler(deltaEuler)
    desiredWorld
      .copy(bodyWorld)
      .multiply(neutralBodyToHead)
      .multiply(deltaQuat)

    head.parent.getWorldQuaternion(parentWorld)
    invParentWorld.copy(parentWorld).invert()
    head.quaternion.copy(invParentWorld).multiply(desiredWorld)
    head.updateMatrix()
  }
}

/** Body link used as the reference frame for head RPY gizmo. */
export function getReachyBodyLink(robot: THREE.Object3D): THREE.Object3D | null {
  return (
    robot.getObjectByName('link_body_down_3dprint') ??
    robot.getObjectByName('link_body_foot_3dprint') ??
    robot
  )
}

/** Head shell link (gizmo follows its world position). */
export function getReachyHeadLink(robot: THREE.Object3D): THREE.Object3D | null {
  return (
    robot.getObjectByName('link_xl_330') ??
    robot.getObjectByName('link_head') ??
    null
  )
}

/**
 * URDF link names whose visual meshes should be hidden in the Reachy Mini 3D
 * viewer.
 *
 * Reachy Mini's neck is a 6-rod Stewart platform — a closed kinematic loop.
 * URDF can only represent trees, so the exported URDF duplicates the loop as
 * 6 separate rod chains hanging off motor horns. Only one of those chains
 * (`stewart_6` via `passive_6/7_*`) is actually parented to the head link;
 * the other 5 rods dangle at their default rotation and visually look
 * "broken" / detached from the head shell. The passive ball-joint pieces at
 * each rod end also look like floating flecks once the rods are gone.
 *
 * Hiding these link visuals (NOT the link groups themselves — that would
 * unparent downstream joints) removes the broken look while keeping the
 * head's pose driven by the one rod that's actually in the kinematic chain.
 *
 * NOTE: when the daemon provides `passive_joints` (21 values solved by Placo
 * closed-loop IK), the Stewart platform closes properly and rods look
 * correctly connected — in that case the caller should pass an empty
 * hiddenLinks list (or use `reachyHiddenLinksForJoints()` helper). This list
 * is only the FALLBACK for when passive joints aren't available (e.g. catalog
 * preview, motion editor without live daemon data).
 */
export const REACHY_MINI_HIDDEN_LINKS: string[] = [
  'stewart_link_rod',
  'stewart_link_rod_2',
  'stewart_link_rod_3',
  'stewart_link_rod_4',
  'stewart_link_rod_5',
  'stewart_link_rod_6',
  'passive_1_link_x',
  'passive_1_link_y',
  'passive_2_link_x',
  'passive_2_link_y',
  'passive_3_link_x',
  'passive_3_link_y',
  'passive_4_link_x',
  'passive_4_link_y',
  'passive_5_link_x',
  'passive_5_link_y',
  'passive_6_link_x',
  'passive_6_link_y',
  'passive_7_link_x',
  'passive_7_link_y',
]

/**
 * The 21 URDF passive-joint names in the exact order the daemon streams them
 * (passive_1_x/y/z, then passive_2_x/y/z, …, passive_7_x/y/z).
 *
 * These are the closed-loop IK solution from Placo (running on the daemon).
 * Applying them alongside the 6 stewart motor joints makes the URDF tree
 * visually close the loop — the 6 rods actually meet the head at the right
 * place, and the head's pose is driven correctly by the kinematic chain
 * (no need for any head-link rotation override).
 *
 * Matches the order used by the official pollen-robotics/reachy-mini-desktop-app.
 */
export const REACHY_MINI_PASSIVE_JOINT_NAMES: string[] = [
  'passive_1_x', 'passive_1_y', 'passive_1_z',
  'passive_2_x', 'passive_2_y', 'passive_2_z',
  'passive_3_x', 'passive_3_y', 'passive_3_z',
  'passive_4_x', 'passive_4_y', 'passive_4_z',
  'passive_5_x', 'passive_5_y', 'passive_5_z',
  'passive_6_x', 'passive_6_y', 'passive_6_z',
  'passive_7_x', 'passive_7_y', 'passive_7_z',
]

/** True if the joint map contains passive_* entries (i.e. daemon has Placo). */
export function hasPassiveJoints(joints: Record<string, number> | null | undefined): boolean {
  if (!joints) return false
  for (const name of REACHY_MINI_PASSIVE_JOINT_NAMES) {
    if (typeof joints[name] === 'number') return true
  }
  return false
}

/**
 * If the daemon's state contains `passive_joints` (21 numbers), merge them
 * into the given URDF joint map under their proper URDF names. Returns a
 * new map; the input is not mutated.
 */
export function mergePassiveJoints(
  joints: Record<string, number>,
  passiveJoints: number[] | null | undefined,
): Record<string, number> {
  if (!Array.isArray(passiveJoints) || passiveJoints.length === 0) return joints
  const out = { ...joints }
  for (let i = 0; i < Math.min(passiveJoints.length, REACHY_MINI_PASSIVE_JOINT_NAMES.length); i++) {
    const v = passiveJoints[i]
    if (typeof v === 'number' && Number.isFinite(v)) {
      out[REACHY_MINI_PASSIVE_JOINT_NAMES[i]] = v
    }
  }
  return out
}
