/**
 * VirtualPlayPanel — pure-frontend "play with this robot in the browser".
 *
 * Loads the URDF, reads joint names + limits from the kinematic tree,
 * renders the 3D viewer + a sidebar of joint sliders + preset pose buttons.
 * No hardware, no Local Agent, no cloud virtual state machine required.
 *
 * This is the baseline "virtual play" for every runtime. Robots with a
 * richer cloud-backed virtual (Reachy Mini) keep that as a separate path;
 * this panel is the universal minimum.
 */
import { useEffect, useMemo, useState } from 'react'
import { Loader2, RotateCcw, Shuffle, Sparkles } from 'lucide-react'
import { Button } from '../ui/button'
import { UrdfViewer, type UrdfJointValues } from '../features/UrdfViewer'
import { loadURDF } from '../../lib/urdf'
import { catalogMeta } from '../../lib/robotCatalog'
import {
  REACHY_MINI_HIDDEN_LINKS,
  createReachyHeadDeltaUpdater,
} from '../../lib/reachyVirtualPreview'

export interface VirtualPreset {
  name: string
  /** Joint name → angle (radians). Joints not listed stay at current value. */
  joints: Record<string, number>
}

export interface VirtualPlayPanelProps {
  urdfUrl: string
  runtimeId: string
  /** Optional presets; if omitted, only "Neutral" + "Random" are shown. */
  presets?: VirtualPreset[]
}

type JointState = {
  name: string
  type: string
  lower: number
  upper: number
  value: number
}

function midpoint(lower: number, upper: number): number {
  return (lower + upper) / 2
}

export function VirtualPlayPanel({ urdfUrl, runtimeId, presets }: VirtualPlayPanelProps) {
  const meta = catalogMeta(runtimeId)
  const isReachy = runtimeId === 'reachy_mini'
  const [joints, setJoints] = useState<JointState[]>([])
  const [jointValues, setJointValues] = useState<UrdfJointValues>({})
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [viewerKey, setViewerKey] = useState(0)

  // Load URDF once to read joint names + limits. STL/URDF caches are shared
  // with the viewer, so the second load inside UrdfViewer is cheap.
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setErr(null)
    loadURDF(urdfUrl, { eagerDisplay: false })
      .then(({ robot }) => {
        if (cancelled) return
        const list: JointState[] = []
        robot.traverse((obj) => {
          const ud = obj.userData as {
            jointType?: string
            axis?: unknown
            limits?: { lower: number; upper: number }
          }
          if (!ud || !ud.jointType || ud.jointType === 'fixed' || !ud.axis) return
          // Reachy Mini: stewart_* + passive_* are one closed-loop mechanism.
          // Without Placo's complete passive-joint solution, changing any of
          // them detaches the head. The generic fallback therefore exposes only
          // yaw_body and antennas; the richer Reachy page handles head RPY.
          if (
            isReachy &&
            (/^passive_\d+_[xyz]$/.test(obj.name) || /^stewart_\d+$/.test(obj.name))
          ) {
            return
          }
          const limits = ud.limits ?? { lower: -Math.PI, upper: Math.PI }
          const lower = Math.max(-Math.PI * 2, limits.lower)
          const upper = Math.min(Math.PI * 2, limits.upper)
          list.push({
            name: obj.name,
            type: ud.jointType,
            lower,
            upper,
            value: midpoint(lower, upper),
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
        const initial: UrdfJointValues = {}
        for (const j of list) initial[j.name] = j.value
        setJointValues(initial)
        setLoading(false)
        // Trigger viewer mount once we have joints to apply
        setViewerKey((k) => k + 1)
      })
      .catch((e) => {
        if (cancelled) return
        setErr((e as Error).message || '加载 URDF 失败')
        setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [urdfUrl, isReachy])

  const setJoint = (name: string, value: number) => {
    setJointValues((prev) => ({ ...prev, [name]: value }))
    setJoints((prev) => prev.map((j) => (j.name === name ? { ...j, value } : j)))
  }

  const reset = () => {
    const next: UrdfJointValues = {}
    for (const j of joints) next[j.name] = midpoint(j.lower, j.upper)
    setJointValues(next)
    setJoints((prev) => prev.map((j) => ({ ...j, value: next[j.name] ?? j.value })))
  }

  const randomize = () => {
    const next: UrdfJointValues = {}
    for (const j of joints) {
      next[j.name] = j.lower + Math.random() * (j.upper - j.lower)
    }
    setJointValues(next)
    setJoints((prev) => prev.map((j) => ({ ...j, value: next[j.name] ?? j.value })))
  }

  const applyPreset = (preset: VirtualPreset) => {
    setJointValues((prev) => ({ ...prev, ...preset.joints }))
    setJoints((prev) =>
      prev.map((j) => ({
        ...j,
        value: preset.joints[j.name] ?? j.value,
      })),
    )
  }

  // Reachy Mini: preserve the URDF's exact neutral head orientation. The old
  // absolute-world override changed that nominal orientation and caused a
  // permanent tilt even at zero.
  const reachyHeadDelta = useMemo(
    () => (isReachy ? createReachyHeadDeltaUpdater() : null),
    [isReachy],
  )
  const afterJointUpdate = useMemo(
    () =>
      reachyHeadDelta
        ? (robot: import('three').Object3D) => {
            reachyHeadDelta(robot, 0, 0, 0)
          }
        : undefined,
    [reachyHeadDelta],
  )

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
      <div className="relative min-h-[460px] overflow-hidden rounded-2xl border border-white/10 bg-[#0c0a09]">
        {viewerKey > 0 && !loading && (
          <UrdfViewer
            key={viewerKey}
            urdfUrl={urdfUrl}
            joints={jointValues}
            className="absolute inset-0 h-full w-full"
            cameraPosition={meta?.stageCameraPosition ?? meta?.cameraPosition}
            orbitTarget={meta?.orbitTarget}
            waitForMeshes
            hideMeshProgress
            meshConcurrency={meta?.meshConcurrency}
            hiddenLinks={isReachy ? REACHY_MINI_HIDDEN_LINKS : undefined}
            afterJointUpdate={afterJointUpdate}
          />
        )}
        {loading && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-stone-500">
            <Loader2 className="h-5 w-5 animate-spin text-[var(--ember)]" />
            <span className="text-[11px]">读取关节定义…</span>
          </div>
        )}
        {meta?.modelCredit && !loading && (
          <span className="pointer-events-none absolute bottom-3 left-1/2 -translate-x-1/2 whitespace-nowrap rounded-full border border-white/10 bg-black/55 px-2 py-1 text-[9px] text-slate-300 backdrop-blur">
            {meta.modelCredit}
          </span>
        )}
      </div>

      <div className="space-y-4">
        <div className="rounded-2xl border border-white/10 bg-white/[0.02] p-4">
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-sm font-medium">虚拟玩法</h3>
            <span className="text-[11px] text-stone-500">
              {loading ? '加载关节…' : `${joints.length} 个关节`}
            </span>
          </div>
          <p className="mt-1 text-xs leading-relaxed text-stone-400">
            拖滑条让模型动。纯前端，不连真机、不装 Agent。
          </p>

          <div className="mt-3 flex flex-wrap gap-2">
            <Button size="sm" variant="outline" onClick={reset} disabled={loading || joints.length === 0}>
              <RotateCcw className="h-3.5 w-3.5" />
              归位
            </Button>
            <Button size="sm" variant="outline" onClick={randomize} disabled={loading || joints.length === 0}>
              <Shuffle className="h-3.5 w-3.5" />
              随机
            </Button>
            {presets?.map((p) => (
              <Button
                key={p.name}
                size="sm"
                variant="ghost"
                onClick={() => applyPreset(p)}
                disabled={loading || joints.length === 0}
              >
                <Sparkles className="h-3.5 w-3.5" />
                {p.name}
              </Button>
            ))}
          </div>
        </div>

        {err && (
          <div className="rounded-xl border border-red-500/30 bg-red-500/5 px-3 py-2 text-xs text-red-200">
            {err}
          </div>
        )}

        <div className="rounded-2xl border border-white/10 bg-black/20 p-4">
          <div className="max-h-[460px] space-y-3 overflow-y-auto pr-1">
            {!loading && joints.length === 0 && (
              <p className="text-xs text-stone-500">这个 URDF 没有可动关节。</p>
            )}
            {joints.map((j) => (
              <label key={j.name} className="block space-y-1">
                <div className="flex items-baseline justify-between text-xs">
                  <span className="font-mono text-stone-300">{j.name}</span>
                  <span className="font-mono tabular-nums text-stone-500">
                    {j.value.toFixed(2)}
                    <span className="ml-1 text-stone-600">rad</span>
                  </span>
                </div>
                <input
                  type="range"
                  min={j.lower}
                  max={j.upper}
                  step={0.01}
                  value={j.value}
                  onChange={(e) => setJoint(j.name, Number(e.target.value))}
                  className="w-full accent-[var(--ember)]"
                />
                <div className="flex justify-between text-[10px] text-stone-600">
                  <span>{j.lower.toFixed(2)}</span>
                  <span>{j.upper.toFixed(2)}</span>
                </div>
              </label>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
