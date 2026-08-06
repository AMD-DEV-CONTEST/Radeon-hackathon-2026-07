/**
 * /robots/:runtimeId/play — universal virtual play page for any runtime.
 *
 * Reads the manifest, picks the URDF, drops in VirtualPlayPanel.
 * One page serves every robot — no per-runtime virtual page needed.
 */
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, Loader2 } from 'lucide-react'
import { VirtualPlayPanel, type VirtualPreset } from '../components/virtual/VirtualPlayPanel'
import { catalogMeta } from '../lib/robotCatalog'
import { listRobotManifests, type RobotManifest } from '../lib/robotApi'
import { FALLBACK_ROBOT_MANIFESTS } from '../lib/fallbackRobots'
import { B601_URDF_CATALOG } from '../lib/b601Urdf'

const FALLBACK_URDF: Record<string, string> = {
  so101: '/api/urdf/so101.urdf',
  reachy_mini: '/api/urdf/reachy_mini/reachy_mini.urdf',
  b601_rs: B601_URDF_CATALOG,
}

// A couple of friendly presets for arms (SO-101 / B601 share similar 6-7 DoF).
// Names are URDF joint names; values are radians.
const ARM_PRESETS: VirtualPreset[] = [
  {
    name: '挥手',
    joints: { '1': 0, '2': -0.6, '3': 1.2, '4': 0.4, '5': 0, '6': 0 },
  },
  {
    name: '收起',
    joints: { '1': 0, '2': 1.2, '3': 1.4, '4': 0, '5': 0, '6': 0 },
  },
]

function presetsFor(runtimeId: string, jointCount: number | undefined): VirtualPreset[] | undefined {
  if (['so101', 'b601_rs', 'b601_dm', 'bi_b601_dm'].includes(runtimeId)) return ARM_PRESETS
  if (runtimeId === 'lekiwi') return ARM_PRESETS
  if (runtimeId === 'amazing_hand') {
    return [
      {
        name: '张开',
        joints: Object.fromEntries(
          Array.from({ length: jointCount ?? 8 }, (_, i) => [String(i + 1), 0.5]),
        ),
      },
      {
        name: '握拳',
        joints: Object.fromEntries(
          Array.from({ length: jointCount ?? 8 }, (_, i) => [String(i + 1), -0.5]),
        ),
      },
    ]
  }
  return undefined
}

export function RobotVirtualPlay() {
  const { runtimeId } = useParams<{ runtimeId: string }>()
  const [manifest, setManifest] = useState<RobotManifest | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const body = await listRobotManifests()
        const found = body.robots.find((r) => r.runtime_id === runtimeId)
        if (!cancelled) setManifest(found ?? null)
      } catch {
        // fall back to FALLBACK_ROBOT_MANIFESTS
        const fb = FALLBACK_ROBOT_MANIFESTS.find((r) => r.runtime_id === runtimeId) ?? null
        if (!cancelled) setManifest(fb)
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [runtimeId])

  if (!runtimeId) {
    return (
      <div className="container mx-auto px-4 py-8 text-sm text-muted-foreground">
        缺少 runtimeId。
      </div>
    )
  }

  const meta = catalogMeta(runtimeId)
  const urdfUrl =
    manifest?.urdf_url ?? FALLBACK_URDF[runtimeId] ?? `/api/urdf/${runtimeId}/${runtimeId}.urdf`

  return (
    <div className="container mx-auto space-y-5 px-4 py-6">
      <div className="bvx-page-header">
        <Link to="/robots" className="bvx-back-link">
          <ArrowLeft className="h-3.5 w-3.5" />
          机器人目录
        </Link>
        <div className="flex items-baseline gap-3">
          <h1 className="bvx-page-title">
            {meta?.title ?? manifest?.display_name ?? runtimeId}
          </h1>
          <span className="bvx-pill bvx-pill--virtual">虚拟玩法</span>
        </div>
        <p className="bvx-page-subtitle">
          浏览器里直接拖动关节。不连真机、不装 Agent、零硬件。
          {manifest?.preview ? '（这台机型当前是 Preview，先在 3D 里玩。）' : ''}
        </p>
      </div>

      {loading ? (
        <div className="flex h-64 items-center justify-center text-sm text-muted-foreground">
          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          加载机型清单…
        </div>
      ) : !urdfUrl ? (
        <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-4 text-sm text-amber-200/90">
          这个机型暂无 URDF，没法在浏览器里玩。先回目录看看其它机型。
        </div>
      ) : (
        <VirtualPlayPanel
          urdfUrl={urdfUrl}
          runtimeId={runtimeId}
          presets={presetsFor(runtimeId, manifest?.joint_count)}
        />
      )}

      <div className="rounded-xl border border-white/10 bg-white/[0.02] p-4 text-xs text-stone-400">
        <p>
          想接真机？{' '}
          {runtimeId === 'so101' ? (
            <Link to="/robots/so101?mode=browser" className="text-[var(--paper)] underline underline-offset-2">
              浏览器直连 SO-101
            </Link>
          ) : (
            <Link to={`/robots/${runtimeId}`} className="text-[var(--paper)] underline underline-offset-2">
              进入 {meta?.title ?? runtimeId} 真机向导
            </Link>
          )}
          ；要录数据、训练时再装 Local Agent。
        </p>
      </div>
    </div>
  )
}
