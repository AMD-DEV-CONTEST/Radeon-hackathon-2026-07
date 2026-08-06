/**
 * T2-2 · 通用工作台壳子
 *
 * 读 manifest 的 capability_tags，从 panelRegistry 渲染对应面板。
 * 这是 LeKiwi 试验田的入口；将来 Reachy / 新机型也走这条路径。
 *
 * 当前阶段：仅框架。LeKiwi 现有页面 (RobotLeKiwi.tsx) 暂不动，等面板逐个迁移完成后再切换。
 *
 * 见 progress/M28-consolidation-execution-plan.md T2-2。
 */
import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import type { RobotManifest } from '../../lib/robotApi'
import { panelsForManifest } from './panelRegistry'

export interface GenericWorkbenchProps {
  manifest: RobotManifest
  /** 顶部 Stage 区域（3D 预览）由调用方传入，避免重复加载 URDF。 */
  stage?: React.ReactNode
  /** 顶部标题，默认用 manifest.display_name。 */
  title?: string
  /** 顶部副标题。 */
  subtitle?: string
}

export function GenericWorkbench({ manifest, stage, title, subtitle }: GenericWorkbenchProps) {
  const panels = useMemo(() => panelsForManifest(manifest), [manifest])

  return (
    <div className="container mx-auto px-4 py-6 space-y-5">
      <div className="flex items-center justify-between gap-3">
        <Link
          to="/robots"
          className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" />
          机器人目录
        </Link>
        <div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
          <span className="rounded-full border border-emerald-400/25 bg-emerald-400/10 px-2.5 py-1 text-emerald-200">
            Generic workbench
          </span>
        </div>
      </div>

      {stage && (
        <section className="relative overflow-hidden rounded-3xl border border-white/10 bg-[#080c14]">
          {stage}
        </section>
      )}

      <div className="space-y-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{title ?? manifest.display_name}</h1>
          {subtitle && <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>}
        </div>

        {panels.length === 0 ? (
          <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-4 text-sm text-amber-200/90">
            该机型 manifest 里没有声明任何 capability_tags，通用工作台没有可渲染的面板。
            请在 <code>apps/realtime/config/robots.json</code> 里给该机型补上
            <code>capability_tags</code>（如 <code>["teleop", "record", "camera"]</code>）。
          </div>
        ) : (
          <div className="grid gap-4 xl:grid-cols-2">
            {panels.map((reg) => {
              const Panel = reg.component
              return <Panel key={reg.id} manifest={manifest} />
            })}
          </div>
        )}
      </div>
    </div>
  )
}
