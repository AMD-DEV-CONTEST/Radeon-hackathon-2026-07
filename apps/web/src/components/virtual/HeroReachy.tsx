/**
 * HeroReachy — homepage Reachy Mini that cycles through many official
 * Pollen / Hugging Face dances + cute emotions (local-mirrored JSON).
 */
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { UrdfViewer, type UrdfJointValues } from '../features/UrdfViewer'
import { loadURDF } from '../../lib/urdf'
import {
  REACHY_MINI_HIDDEN_LINKS,
  createReachyHeadDeltaUpdater,
} from '../../lib/reachyVirtualPreview'
import {
  moveJsonToClip,
  interpolatePose,
  NEUTRAL_POSE,
  type ReachyMotionClip,
  type ReachyPoseFrame,
} from '../../lib/reachyMotionClip'

const HERO_URDF = '/api/urdf/reachy_mini/reachy_mini.urdf'

// Cute-first playlist: official dances + emotions mirrored under
// apps/realtime/data/reachy_mini_moves/{dances,emotions}/
const PLAYLIST: Array<{ name: string; label: string }> = [
  // greetings & cute vibes
  { name: 'hello', label: '挥手打招呼' },
  { name: 'welcoming1', label: '欢迎欢迎' },
  { name: 'wiggle', label: '开心扭扭' },
  { name: 'happy', label: '开心得跳' },
  { name: 'cheerful1', label: '元气满满' },
  { name: 'excited', label: '超级兴奋' },
  { name: 'laughing1', label: '哈哈大笑' },
  { name: 'laughing2', label: '咯咯笑' },
  { name: 'shy1', label: '害羞一下' },
  { name: 'loving1', label: '比心一下' },
  { name: 'surprised1', label: '哇！惊喜' },
  { name: 'surprised2', label: '又惊喜' },
  { name: 'oops1', label: '哎呀出错' },
  { name: 'yes1', label: '用力点头' },
  { name: 'proud1', label: '得意一下' },
  { name: 'enthusiastic1', label: '热情回应' },
  { name: 'helpful1', label: '热心帮忙' },
  { name: 'no_excited1', label: '兴奋摇头' },
  // official dance library (cute / expressive first)
  { name: 'chicken_peck', label: '小鸡啄米' },
  { name: 'side_peekaboo', label: '躲猫猫' },
  { name: 'yeah_nod', label: 'Yeah 点头' },
  { name: 'uh_huh_tilt', label: '嗯嗯歪头' },
  { name: 'side_glance_flick', label: '偷看一眼' },
  { name: 'neck_recoil', label: '吓一跳' },
  { name: 'simple_nod', label: '轻轻点头' },
  { name: 'nod', label: '点头同意' },
  { name: 'shake', label: '摇头否定' },
  { name: 'dizzy_spin', label: '晕乎乎转' },
  { name: 'pendulum_swing', label: '钟摆摇摆' },
  { name: 'side_to_side_sway', label: '左右晃' },
  { name: 'groovy_sway_and_roll', label: '律动摇摆' },
  { name: 'chin_lead', label: '下巴领舞' },
  { name: 'head_tilt_roll', label: '歪头翻滚' },
  { name: 'sharp_side_tilt', label: '侧倾一下' },
  { name: 'stumble_and_recover', label: '踉跄回稳' },
  { name: 'grid_snap', label: '卡点切换' },
  { name: 'polyrhythm_combo', label: '复合节奏' },
  { name: 'dance1', label: '小段舞步' },
  { name: 'interwoven_spirals', label: '交织螺旋' },
  { name: 'jackson_square', label: '方形卡点' },
]

const MOVE_API = (name: string) => `/api/reachy/move/local-moves/get/${encodeURIComponent(name)}`

/** Pause after a move finishes, before picking the next cute clip. */
const PAUSE_BETWEEN_MOVES = 0.55
/** Don't let a single long emotion monopolize the hero forever. */
const MAX_PLAY_SECONDS = 6.5

type JointSpec = { name: string; lower: number; upper: number }

export function HeroReachy() {
  const [joints, setJoints] = useState<JointSpec[]>([])
  const [clip, setClip] = useState<ReachyMotionClip | null>(null)
  const [clipLabel, setClipLabel] = useState<string>('')
  const [ready, setReady] = useState(false)
  const [currentPose, setCurrentPose] = useState<ReachyPoseFrame>(NEUTRAL_POSE)

  // Cached fetched moves so we don't refetch on every cycle.
  const clipCache = useRef<Map<string, ReachyMotionClip>>(new Map())
  // Current playback timing.
  const playStateRef = useRef<{ clip: ReachyMotionClip; startedAt: number } | null>(null)
  const playlistIdxRef = useRef(0)
  const rafRef = useRef<number | null>(null)
  // Live pose ref — read by afterJointUpdate closure (which is captured by
  // UrdfViewer's useFrame) without forcing a new closure each tick.
  const poseRef = useRef<ReachyPoseFrame>(NEUTRAL_POSE)
  useLayoutEffect(() => {
    poseRef.current = currentPose
  }, [currentPose])

  // Load URDF once to read joint names + limits.
  useEffect(() => {
    let cancelled = false
    loadURDF(HERO_URDF, { eagerDisplay: false })
      .then(({ robot }) => {
        if (cancelled) return
        const list: JointSpec[] = []
        robot.traverse((obj) => {
          const ud = obj.userData as {
            jointType?: string
            axis?: unknown
            limits?: { lower: number; upper: number }
          }
          if (!ud || !ud.jointType || ud.jointType === 'fixed' || !ud.axis) return
          const limits = ud.limits ?? { lower: -Math.PI, upper: Math.PI }
          list.push({
            name: obj.name,
            lower: Math.max(-Math.PI * 2, limits.lower),
            upper: Math.min(Math.PI * 2, limits.upper),
          })
        })
        if (cancelled) return
        list.sort((a, b) => {
          const an = Number(a.name)
          const bn = Number(b.name)
          if (Number.isFinite(an) && Number.isFinite(bn)) return an - bn
          return a.name.localeCompare(b.name)
        })
        setJoints(list)
        setReady(true)
      })
      .catch(() => setReady(true))
    return () => {
      cancelled = true
    }
  }, [])

  // Fetch one move JSON, cache it.
  const fetchClip = useCallback(async (name: string): Promise<ReachyMotionClip | null> => {
    const cached = clipCache.current.get(name)
    if (cached) return cached
    try {
      const res = await fetch(MOVE_API(name))
      if (!res.ok) return null
      const json = await res.json()
      const clip = moveJsonToClip(json)
      clipCache.current.set(name, clip)
      return clip
    } catch {
      return null
    }
  }, [])

  // Main playback loop: cycle through PLAYLIST, sample clip via rAF.
  useEffect(() => {
    if (!ready || joints.length === 0) return
    let cancelled = false

    const playNext = async () => {
      if (cancelled) return
      let nextIndex = Math.floor(Math.random() * PLAYLIST.length)
      if (PLAYLIST.length > 1 && nextIndex === playlistIdxRef.current) {
        nextIndex = (nextIndex + 1) % PLAYLIST.length
      }
      playlistIdxRef.current = nextIndex
      const entry = PLAYLIST[nextIndex]!
      const c = await fetchClip(entry.name)
      if (cancelled) return
      if (!c) {
        // Skip missing moves; advance and try next after a short delay.
        setTimeout(playNext, 200)
        return
      }
      setClip(c)
      setClipLabel(entry.label)
      playStateRef.current = { clip: c, startedAt: performance.now() / 1000 }
    }

    const tick = () => {
      if (cancelled) return
      const state = playStateRef.current
      if (state) {
        const now = performance.now() / 1000
        const t = now - state.startedAt
        const playFor = Math.min(state.clip.duration, MAX_PLAY_SECONDS)
        const slotEnd = playFor + PAUSE_BETWEEN_MOVES
        if (t >= slotEnd) {
          playStateRef.current = null
          void playNext()
        } else if (t <= playFor) {
          setCurrentPose(interpolatePose(state.clip, t))
        } else {
          // Ease back toward URDF neutral during the short pause.
          const pauseT = (t - playFor) / Math.max(PAUSE_BETWEEN_MOVES, 0.001)
          const lastPose = interpolatePose(state.clip, playFor)
          const blend = Math.min(1, pauseT)
          setCurrentPose({
            head: {
              roll: lastPose.head.roll * (1 - blend),
              pitch: lastPose.head.pitch * (1 - blend),
              yaw: lastPose.head.yaw * (1 - blend),
            },
            bodyYaw: lastPose.bodyYaw * (1 - blend),
            antennas: [
              lastPose.antennas[0] * (1 - blend),
              lastPose.antennas[1] * (1 - blend),
            ],
          })
        }
      }
      rafRef.current = requestAnimationFrame(tick)
    }

    void playNext()
    rafRef.current = requestAnimationFrame(tick)
    return () => {
      cancelled = true
      if (rafRef.current) cancelAnimationFrame(rafRef.current)
    }
  }, [ready, joints, fetchClip])

  // Preserve the URDF zero pose exactly. Without Placo's passive-joint IK,
  // touching stewart_* or passive_* moves the head's parent chain and detaches
  // the shell. Only body yaw + antennas are safe tree joints; head RPY is
  // applied later as a rotation delta on the shell itself.
  const jointValues = useMemo<UrdfJointValues>(() => {
    const out: UrdfJointValues = {}
    for (const j of joints) out[j.name] = 0
    out.yaw_body = currentPose.bodyYaw
    out.right_antenna = currentPose.antennas[1] ?? 0
    out.left_antenna = currentPose.antennas[0] ?? 0
    return out
  }, [joints, currentPose])

  // Capture the untouched URDF head orientation as neutral, then apply dance
  // RPY only as a delta. This keeps both position and nominal orientation.
  const updateHeadDelta = useMemo(() => createReachyHeadDeltaUpdater(), [])
  const afterJointUpdate = useCallback((robot: import('three').Object3D) => {
    const pose = poseRef.current
    updateHeadDelta(robot, pose.head.roll, pose.head.pitch, pose.head.yaw)
  }, [updateHeadDelta])

  const camera = useMemo<[number, number, number]>(() => [0.42, 0.4, 0.42], [])
  const orbit = useMemo<[number, number, number]>(() => [0, 0.12, 0], [])

  return (
    <div className="absolute inset-0">
      {ready && (
        <UrdfViewer
          urdfUrl={HERO_URDF}
          joints={jointValues}
          className="absolute inset-0 h-full w-full"
          cameraPosition={camera}
          orbitTarget={orbit}
          waitForMeshes
          hideMeshProgress
          meshConcurrency={8}
          hiddenLinks={REACHY_MINI_HIDDEN_LINKS}
          afterJointUpdate={afterJointUpdate}
          jointSmoothing={12}
        />
      )}
      <span className="pointer-events-none absolute bottom-3 left-1/2 -translate-x-1/2 whitespace-nowrap rounded-full border border-[var(--ember)]/25 bg-[#05070c]/70 px-2.5 py-1 text-[10px] text-slate-200 backdrop-blur">
        {clip ? `正在跳：${clipLabel}` : '加载可爱动作…'}
      </span>
    </div>
  )
}
