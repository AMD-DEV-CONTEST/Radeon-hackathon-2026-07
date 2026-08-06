import { memo, useEffect, useRef, useState, useCallback } from 'react'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { OrbitControls } from '@react-three/drei'
import { Loader2 } from 'lucide-react'
import * as THREE from 'three'
import { loadURDF, updateRobotJoints, clearStlCache, hideLinkVisualsMany } from '../../lib/urdf'
import { cn } from '../../lib/utils'

const DEFAULT_URDF_URL = '/api/urdf/so101.urdf'

export type UrdfJointValues = Record<string, number | undefined>

interface UrdfViewerProps {
  urdfUrl?: string
  joints?: UrdfJointValues | null
  className?: string
  /** Camera position in scene units (default tuned for SO-101 arm). */
  cameraPosition?: [number, number, number]
  /** OrbitControls look-at target. */
  orbitTarget?: [number, number, number]
  /** Smoothing rate for joint interpolation (lower = less jitter). */
  jointSmoothing?: number
  /** Wait for all STL meshes before showing the model (clean catalog previews). */
  waitForMeshes?: boolean
  meshConcurrency?: number
  hideMeshProgress?: boolean
  onFullyLoaded?: () => void
  onMeshFailed?: (meshUrl: string) => void
  /**
   * URDF link names whose visual meshes should be hidden after load.
   *
   * The link groups themselves stay in the scene graph (so child joints/links
   * keep working), only their direct visual sub-groups are set invisible.
   * Useful for closed-loop mechanisms (e.g. Reachy Mini's Stewart platform)
   * where dangling rods would otherwise look "broken".
   */
  hiddenLinks?: string[]
  /**
   * Optional callback invoked in the render loop AFTER `updateRobotJoints`
   * has applied the current joint values. Use this to override transforms
   * that the URDF kinematic tree can't represent — e.g. Reachy Mini's
   * closed-loop Stewart head, where pitch/roll get lost because URDF can
   * only express one of the 6 rods as the head's parent.
   */
  afterJointUpdate?: (robot: THREE.Object3D) => void
}

function FrameInvalidator({ tick }: { tick: number }) {
  const invalidate = useThree((s) => s.invalidate)
  useEffect(() => {
    invalidate()
  }, [invalidate, tick])
  return null
}

function RobotNode({
  robot,
  joints,
  jointSmoothing = 22,
  afterJointUpdate,
}: {
  robot: THREE.Group | null
  joints?: UrdfJointValues | null
  jointSmoothing?: number
  afterJointUpdate?: (robot: THREE.Object3D) => void
}) {
  const smoothed = useRef<Record<string, number>>({})
  const targetRef = useRef<Record<string, number>>({})
  const invalidate = useThree((s) => s.invalidate)
  const afterRef = useRef(afterJointUpdate)
  afterRef.current = afterJointUpdate

  useEffect(() => {
    if (!joints) return
    const next: Record<string, number> = {}
    for (const [name, value] of Object.entries(joints)) {
      if (typeof value === 'number' && Number.isFinite(value)) next[name] = value
    }
    targetRef.current = next
  }, [joints])

  useFrame((_, delta) => {
    if (!robot) return
    const target = targetRef.current
    const keys = Object.keys(target)
    if (keys.length) {
      const blend = Math.min(1, delta * jointSmoothing)
      const out: Record<string, number> = {}
      for (const name of keys) {
        const t = target[name]
        const prev = smoothed.current[name]
        const cur = prev === undefined ? t : prev + (t - prev) * blend
        smoothed.current[name] = cur
        out[name] = cur
      }
      updateRobotJoints(robot, out)
      robot.updateMatrixWorld(true)
    }
    // Always run the post-update hook (even with no joint changes) so the
    // caller can override transforms that depend on smoothed joint state.
    afterRef.current?.(robot)
    invalidate()
  })

  if (!robot) return null
  return <primitive object={robot} />
}

function UrdfViewerInner({
  urdfUrl = DEFAULT_URDF_URL,
  joints,
  className,
  cameraPosition = [0.6, 0.6, 0.6],
  orbitTarget = [0, 0.1, 0],
  jointSmoothing = 22,
  waitForMeshes = false,
  meshConcurrency,
  hideMeshProgress = false,
  onFullyLoaded,
  onMeshFailed,
  hiddenLinks,
  afterJointUpdate,
}: UrdfViewerProps) {
  const [robot, setRobot] = useState<THREE.Group | null>(null)
  const robotRef = useRef<THREE.Group | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [webglLost, setWebglLost] = useState(false)
  const [glKey, setGlKey] = useState(0)
  const [loadKey, setLoadKey] = useState(0)
  const [meshProgress, setMeshProgress] = useState<{ loaded: number; total: number } | null>(null)
  const [meshesDone, setMeshesDone] = useState(false)
  const [failedMeshes, setFailedMeshes] = useState<string[]>([])
  const [invalidateTick, setInvalidateTick] = useState(0)

  const onLoadedRef = useRef(onFullyLoaded)
  onLoadedRef.current = onFullyLoaded
  const onMeshFailedRef = useRef(onMeshFailed)
  onMeshFailedRef.current = onMeshFailed

  useEffect(() => {
    let cancelled = false
    setErr(null)
    setRobot(null)
    setMeshProgress(null)
    setMeshesDone(false)
    setFailedMeshes([])

    loadURDF(urdfUrl, {
      eagerDisplay: !waitForMeshes,
      meshConcurrency,
      onMeshProgress: hideMeshProgress
        ? undefined
        : (loaded, total) => {
            if (!cancelled) {
              setMeshProgress({ loaded, total })
              setInvalidateTick((t) => t + 1)
            }
          },
      onMeshFailed: (url) => {
        if (!cancelled) {
          setFailedMeshes((prev) => (prev.includes(url) ? prev : [...prev, url]))
          onMeshFailedRef.current?.(url)
          setInvalidateTick((t) => t + 1)
        }
      },
    })
      .then(async ({ robot: r, meshesReady }) => {
        if (cancelled) return
        if (waitForMeshes) {
          await meshesReady
          if (cancelled) return
          setMeshesDone(true)
        }
        if (hiddenLinks && hiddenLinks.length) {
          hideLinkVisualsMany(r, hiddenLinks)
        }
        // Apply initial joint state immediately (official desktop app inits all
        // joints to zero before first paint to avoid the default URDF tilt).
        if (joints && Object.keys(joints).length) {
          updateRobotJoints(r, joints as Record<string, number>)
          r.updateMatrixWorld(true)
        }
        setRobot(r)
        robotRef.current = r
        setInvalidateTick((t) => t + 1)
        onLoadedRef.current?.()
      })
      .catch((e) => {
        if (cancelled) return
        console.error('[UrdfViewer] load failed', e)
        setErr((e as Error).message)
        onLoadedRef.current?.()
      })

    return () => {
      cancelled = true
      const r = robotRef.current
      robotRef.current = null
      if (r) {
        r.traverse((obj) => {
          const mesh = obj as THREE.Mesh
          if (mesh.geometry) mesh.geometry.dispose()
          if (mesh.material) {
            const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material]
            mats.forEach((m) => m.dispose())
          }
        })
      }
    }
  }, [urdfUrl, waitForMeshes, meshConcurrency, hideMeshProgress, loadKey])

  useEffect(() => {
    if (joints) setInvalidateTick((t) => t + 1)
  }, [joints])

  const onCreated = useCallback(({ gl }: { gl: THREE.WebGLRenderer }) => {
    const canvas = gl.domElement
    const onLost = (event: Event) => {
      event.preventDefault()
      console.warn('[UrdfViewer] WebGL context lost')
      setWebglLost(true)
    }
    const onRestored = () => {
      console.info('[UrdfViewer] WebGL context restored')
      setWebglLost(false)
    }
    canvas.addEventListener('webglcontextlost', onLost)
    canvas.addEventListener('webglcontextrestored', onRestored)
  }, [])

  const recoverWebgl = useCallback(() => {
    clearStlCache('b601_rs')
    clearStlCache('so101')
    clearStlCache('reachy')
    setWebglLost(false)
    setGlKey((k) => k + 1)
    setLoadKey((k) => k + 1)
  }, [])

  const meshesLoading =
    !waitForMeshes &&
    meshProgress !== null &&
    meshProgress.total > 0 &&
    meshProgress.loaded < meshProgress.total

  const showCanvas = robot && (!waitForMeshes || meshesDone)

  return (
    <div
      className={cn(
        'relative w-full h-full min-h-[200px] overflow-hidden rounded-lg bg-[#0b0f1a]',
        className,
      )}
    >
      {err && (
        <div className="absolute top-2 left-2 z-10 px-3 py-1.5 rounded-md bg-red-500/20 border border-red-500/30 text-red-300 text-xs">
          模型加载失败：{err}
        </div>
      )}
      {!showCanvas && !err && (
        <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-2 text-muted-foreground text-sm pointer-events-none">
          <Loader2 className="h-5 w-5 animate-spin text-[hsl(var(--primary))]" />
          <span className="text-xs">加载 3D 模型…</span>
        </div>
      )}
      {robot && meshesLoading && !hideMeshProgress && (
        <div className="absolute bottom-2 right-2 z-10 px-2 py-1 rounded bg-black/50 border border-white/10 text-[10px] text-slate-300">
          零件 {meshProgress.loaded}/{meshProgress.total}
        </div>
      )}
      {failedMeshes.length > 0 && (
        <div className="absolute top-2 right-2 z-10 max-w-[220px] rounded bg-red-950/80 border border-red-500/40 px-2 py-1 text-[10px] text-red-200">
          {failedMeshes.length} 个零件加载失败（红色标记）
        </div>
      )}
      {webglLost && (
        <div className="absolute inset-0 z-20 flex flex-col items-center justify-center gap-2 bg-[#0b0f1a]/90 px-4 text-center">
          <span className="text-amber-400 text-sm font-medium">3D 渲染器因 GPU 过载中断</span>
          <span className="text-xs text-muted-foreground">
            模型零件较多，浏览器 GPU 可能暂时中断；点下方恢复即可，不必刷新整页
          </span>
          <button
            type="button"
            className="px-3 py-1.5 rounded bg-amber-500/20 border border-amber-500/40 text-amber-300 text-xs hover:bg-amber-500/30 transition-colors"
            onClick={recoverWebgl}
          >
            恢复 3D 视图
          </button>
        </div>
      )}

      {showCanvas && (
        <Canvas
          key={glKey}
          style={{ width: '100%', height: '100%', display: 'block' }}
          camera={{ position: cameraPosition, fov: 50, near: 0.01, far: 50 }}
          onCreated={onCreated}
          frameloop="demand"
          dpr={[1, 1.5]}
          resize={{ scroll: false, debounce: { scroll: 50, resize: 0 } }}
          gl={{
            antialias: true,
            alpha: false,
            powerPreference: 'high-performance',
            failIfMajorPerformanceCaveat: false,
          }}
        >
          <color attach="background" args={['#05070c']} />
          <hemisphereLight color="#dbeafe" groundColor="#0a1018" intensity={1.1} />
          <directionalLight position={[2.5, 4, 3]} intensity={1.45} color="#ffffff" />
          <directionalLight position={[-2, 1.5, -1.5]} intensity={0.45} color="#f0742e" />
          <FrameInvalidator tick={invalidateTick} />
          <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.02, 0]}>
            <planeGeometry args={[2.5, 2.5]} />
            <meshStandardMaterial color="#0a1018" roughness={0.92} metalness={0.08} />
          </mesh>
          <gridHelper args={[2.5, 24, '#1e3348', '#101826']} position={[0, -0.019, 0]} />
          <RobotNode
            robot={robot}
            joints={joints}
            jointSmoothing={jointSmoothing}
            afterJointUpdate={afterJointUpdate}
          />
          <OrbitControls
            target={orbitTarget}
            enableDamping
            dampingFactor={0.08}
            makeDefault
            onChange={() => setInvalidateTick((t) => t + 1)}
          />
        </Canvas>
      )}
    </div>
  )
}

export const UrdfViewer = memo(UrdfViewerInner)
