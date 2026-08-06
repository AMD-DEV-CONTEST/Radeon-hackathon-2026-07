/** B601-RS URDF revolute limits (rad) — keep in sync with b601_rs.urdf */
export const B601_ARM_JOINTS = [
  { id: 'joint1', label: '底座旋转', min: -2.8, max: 2.8 },
  // Seeed/DM: shoulder_lift & elbow_flex soft limits are mostly negative (not [0,π]).
  // Must stay in sync with b601_rs*.urdf — UrdfViewer clamps to URDF limits.
  { id: 'joint2', label: '大臂', min: -3.14, max: 0.05 },
  // Symmetric limits: display may negate motor angle (B601_DISPLAY_SIGN).
  { id: 'joint3', label: '小臂', min: -3.5, max: 3.5 },
  { id: 'joint4', label: '腕部1', min: -1.57, max: 1.57 },
  { id: 'joint5', label: '腕部2', min: -1.57, max: 1.57 },
  { id: 'joint6', label: '腕部3', min: -3.14, max: 3.14 },
  { id: 'joint7', label: '夹爪', min: 0, max: 0.05 },
] as const

/**
 * Official calibration zero (Seeed / LeRobot): sit-down pose, gripper closed → all joint angles 0 rad.
 * Used for 3D preview only; does not read or write real motors.
 */
export const B601_ZERO_POSE: Record<string, number> = {
  joint1: 0,
  joint2: 0,
  joint3: 0,
  joint4: 0,
  joint5: 0,
  joint6: 0,
  joint7: 0,
}

export function b601DefaultJointPose(): Record<string, number> {
  return { ...B601_ZERO_POSE }
}

/**
 * Motor rad → URDF visual sign (Seeed/Damiao vs SolidWorks export).
 * Pan (joint1) matches; lift is handled by URDF joint2 axis; elbow/wrist need * -1 here.
 * Limits on those joints are symmetric so negation does not clamp.
 */
export const B601_DISPLAY_SIGN: Record<string, number> = {
  joint1: 1,
  joint2: 1,
  joint3: -1,
  joint4: -1,
  joint5: -1,
  joint6: -1,
  joint7: 1,
}

/** @deprecated alias — use B601_DISPLAY_SIGN for 3D */
export const B601_MOTOR_DIRECTION = B601_DISPLAY_SIGN

/**
 * Optional offset for 3D/slider display after 「读取从臂」: show current pose as all zeros.
 * Uses raw motor radians minus baseline — no sign flip (teleop/GC streams are already motor space).
 */
export function b601MotorRadToUrdf(
  motor: Record<string, number> | null,
  motorZero?: Record<string, number> | null,
): Record<string, number> | null {
  if (!motor) return null
  const out: Record<string, number> = { ...B601_ZERO_POSE }
  for (const j of B601_ARM_JOINTS) {
    const raw = motor[j.id]
    if (raw === undefined || !Number.isFinite(raw)) continue
    const z = motorZero?.[j.id] ?? 0
    out[j.id] = raw - z
  }
  return out
}

/** Raw motor joints → URDF viewer (same path as teleop live stream). */
export function b601MotorJointsForViewer(
  motor: Record<string, number> | null,
  motorZero?: Record<string, number> | null,
): Record<string, number> | null {
  if (!motor) return null
  if (!motorZero) return motor
  return b601MotorRadToUrdf(motor, motorZero)
}

/** Map motor/API names (joint1..joint7) to URDF joint names for the 3D viewer. */
export function b601JointsToUrdf(joints: Record<string, number> | null): Record<string, number> | null {
  if (!joints) return null
  const out: Record<string, number> = {}
  for (let i = 1; i <= 6; i++) {
    const k = `joint${i}`
    if (joints[k] === undefined) continue
    const sign = B601_DISPLAY_SIGN[k] ?? 1
    out[k] = joints[k] * sign
  }
  if (joints.joint7 !== undefined) {
    // Seeed/DM gripper motor space is ≤0 (closed≈0); URDF prismatic wants 0..0.05 m open.
    // Dataset playback may already be meters; live teleop is radians (sometimes |g|>0.25 ≈ degrees leftover).
    const gAbs = Math.abs(joints.joint7)
    const g =
      gAbs > 0.25
        ? Math.min(0.05, (gAbs / 25) * 0.05)
        : Math.min(0.05, gAbs)
    out.gripper_joint1 = g
    out.gripper_joint2 = Math.min(0.0715, g * (0.0715 / 0.05))
  }
  return out
}
