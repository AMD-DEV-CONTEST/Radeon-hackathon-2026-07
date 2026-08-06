import { extractHeadRpyFromPose } from './reachyVirtualPreview'

export interface ReachyHeadRpy {
  roll: number
  pitch: number
  yaw: number
}

/** Task-space pose matching daemon move JSON frames. */
export interface ReachyPoseFrame {
  head: ReachyHeadRpy
  bodyYaw: number
  /** [left, right] — same order as recorded custom moves. */
  antennas: [number, number]
}

export interface ReachyMotionKeyframe {
  t: number
  pose: ReachyPoseFrame
}

export interface ReachyMotionClip {
  duration: number
  keyframes: ReachyMotionKeyframe[]
  displayName?: string
}

export type ReachyEditPart = 'head' | 'body' | 'leftAntenna' | 'rightAntenna'

export interface ReachyMoveJson {
  description?: string
  display_name?: string
  time: number[]
  set_target_data: Array<{
    head: ReachyHeadRpy | number[][]
    antennas: [number, number]
    body_yaw: number
  }>
}

export const NEUTRAL_POSE: ReachyPoseFrame = {
  head: { roll: 0, pitch: 0, yaw: 0 },
  bodyYaw: 0,
  antennas: [0, 0],
}

export const HEAD_LIMIT = 1.57
export const BODY_YAW_LIMIT = Math.PI
export const ANTENNA_LIMIT = Math.PI

export function clampPose(pose: ReachyPoseFrame): ReachyPoseFrame {
  const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v))
  return {
    head: {
      roll: clamp(pose.head.roll, -HEAD_LIMIT, HEAD_LIMIT),
      pitch: clamp(pose.head.pitch, -HEAD_LIMIT, HEAD_LIMIT),
      yaw: clamp(pose.head.yaw, -HEAD_LIMIT, HEAD_LIMIT),
    },
    bodyYaw: clamp(pose.bodyYaw, -BODY_YAW_LIMIT, BODY_YAW_LIMIT),
    antennas: [
      clamp(pose.antennas[0], -ANTENNA_LIMIT, ANTENNA_LIMIT),
      clamp(pose.antennas[1], -ANTENNA_LIMIT, ANTENNA_LIMIT),
    ],
  }
}

/** Minimum-jerk scalar blend (0 at a, 1 at b). */
function minJerkScalar(t: number, t0: number, t1: number): number {
  if (t1 <= t0) return t >= t0 ? 1 : 0
  if (t <= t0) return 0
  if (t >= t1) return 1
  const tau = (t - t0) / (t1 - t0)
  return 10 * tau ** 3 - 15 * tau ** 4 + 6 * tau ** 5
}

function lerp(a: number, b: number, s: number): number {
  return a + (b - a) * s
}

function sortedKeyframes(clip: ReachyMotionClip): ReachyMotionKeyframe[] {
  return [...clip.keyframes].sort((a, b) => a.t - b.t)
}

export function createDefaultClip(duration = 3): ReachyMotionClip {
  return {
    duration,
    keyframes: [
      { t: 0, pose: { ...NEUTRAL_POSE, head: { ...NEUTRAL_POSE.head }, antennas: [0, 0] } },
      { t: duration, pose: { ...NEUTRAL_POSE, head: { ...NEUTRAL_POSE.head }, antennas: [0, 0] } },
    ],
  }
}

export function interpolatePose(clip: ReachyMotionClip, t: number): ReachyPoseFrame {
  const keys = sortedKeyframes(clip)
  if (!keys.length) return NEUTRAL_POSE
  const clampedT = Math.max(0, Math.min(clip.duration, t))

  if (clampedT <= keys[0].t) return clampPose(keys[0].pose)
  if (clampedT >= keys[keys.length - 1].t) return clampPose(keys[keys.length - 1].pose)

  for (let i = 0; i < keys.length - 1; i += 1) {
    const a = keys[i]
    const b = keys[i + 1]
    if (clampedT < a.t || clampedT > b.t) continue
    const s = minJerkScalar(clampedT, a.t, b.t)
    return clampPose({
      head: {
        roll: lerp(a.pose.head.roll, b.pose.head.roll, s),
        pitch: lerp(a.pose.head.pitch, b.pose.head.pitch, s),
        yaw: lerp(a.pose.head.yaw, b.pose.head.yaw, s),
      },
      bodyYaw: lerp(a.pose.bodyYaw, b.pose.bodyYaw, s),
      antennas: [
        lerp(a.pose.antennas[0], b.pose.antennas[0], s),
        lerp(a.pose.antennas[1], b.pose.antennas[1], s),
      ],
    })
  }

  return clampPose(keys[keys.length - 1].pose)
}

function frameToMoveData(pose: ReachyPoseFrame) {
  return {
    head: { ...pose.head },
    antennas: [pose.antennas[0], pose.antennas[1]] as [number, number],
    body_yaw: pose.bodyYaw,
  }
}

export function poseToMoveJson(
  clip: ReachyMotionClip,
  options?: { densifyHz?: number; description?: string },
): ReachyMoveJson {
  const densifyHz = options?.densifyHz
  const keys = sortedKeyframes(clip)
  if (!keys.length) {
    return {
      description: options?.description ?? clip.displayName ?? 'composed move',
      display_name: clip.displayName,
      time: [0],
      set_target_data: [frameToMoveData(NEUTRAL_POSE)],
    }
  }

  if (densifyHz && densifyHz > 0) {
    const dt = 1 / densifyHz
    const times: number[] = []
    const frames: ReachyMoveJson['set_target_data'] = []
    for (let t = 0; t <= clip.duration + 1e-6; t += dt) {
      const sampleT = Math.min(t, clip.duration)
      times.push(Number(sampleT.toFixed(4)))
      frames.push(frameToMoveData(interpolatePose(clip, sampleT)))
    }
    if (times[times.length - 1] < clip.duration) {
      times.push(clip.duration)
      frames.push(frameToMoveData(interpolatePose(clip, clip.duration)))
    }
    return {
      description: options?.description ?? clip.displayName ?? 'composed move',
      display_name: clip.displayName,
      time: times,
      set_target_data: frames,
    }
  }

  return {
    description: options?.description ?? clip.displayName ?? 'composed move',
    display_name: clip.displayName,
    time: keys.map((k) => k.t),
    set_target_data: keys.map((k) => frameToMoveData(k.pose)),
  }
}

function moveHeadToRpy(head: unknown): ReachyHeadRpy {
  return extractHeadRpyFromPose(head as ReachyMoveJson['set_target_data'][0]['head'])
}

export function moveJsonToClip(data: ReachyMoveJson | {
  description?: string
  display_name?: string
  time?: number[]
  set_target_data?: Array<{
    head: unknown
    antennas?: number[]
    body_yaw?: number
  }>
}): ReachyMotionClip {
  const times = data.time ?? []
  const frames = data.set_target_data ?? []
  const keyframes: ReachyMotionKeyframe[] = []
  const n = Math.min(times.length, frames.length)

  for (let i = 0; i < n; i += 1) {
    const frame = frames[i]
    const antennas = frame.antennas ?? [0, 0]
    keyframes.push({
      t: times[i],
      pose: clampPose({
        head: moveHeadToRpy(frame.head),
        bodyYaw: typeof frame.body_yaw === 'number' ? frame.body_yaw : 0,
        antennas: [
          typeof antennas[0] === 'number' ? antennas[0] : 0,
          typeof antennas[1] === 'number' ? antennas[1] : 0,
        ],
      }),
    })
  }

  const duration = times.length ? times[times.length - 1] : 0
  return {
    duration,
    keyframes,
    displayName: data.display_name ?? data.description,
  }
}

export function upsertKeyframe(clip: ReachyMotionClip, t: number, pose: ReachyPoseFrame): ReachyMotionClip {
  const clampedT = Math.max(0, Math.min(clip.duration, t))
  const snapped = Math.round(clampedT * 10) / 10
  const next = clip.keyframes.filter((k) => Math.abs(k.t - snapped) > 0.001)
  next.push({ t: snapped, pose: clampPose(pose) })
  next.sort((a, b) => a.t - b.t)
  return { ...clip, keyframes: next }
}

export function deleteKeyframeAt(clip: ReachyMotionClip, t: number): ReachyMotionClip {
  return {
    ...clip,
    keyframes: clip.keyframes.filter((k) => Math.abs(k.t - t) > 0.001),
  }
}

export function findKeyframeAt(clip: ReachyMotionClip, t: number): ReachyMotionKeyframe | null {
  return clip.keyframes.find((k) => Math.abs(k.t - t) < 0.05) ?? null
}
