import type { LucideIcon } from 'lucide-react'
import { Bot } from 'lucide-react'
import { catalogMeta } from '../../lib/robotCatalog'

/** Static catalog art — no WebGL, no loading overlay, never blocks clicks. */
export function RobotCatalogVisual({ runtimeId }: { runtimeId: string }) {
  const meta = catalogMeta(runtimeId)
  const Icon: LucideIcon = meta?.icon ?? Bot

  const accent =
    runtimeId === 'reachy_mini'
      ? 'from-violet-500/15 via-[hsl(var(--primary))]/10 to-[#0b0f1a]'
      : runtimeId === 'b601_rs'
        ? 'from-slate-500/20 via-[hsl(var(--primary))]/12 to-[#0b0f1a]'
        : 'from-[hsl(var(--primary))]/20 via-amber-500/10 to-[#0b0f1a]'

  return (
    <div
      className={`relative flex h-[220px] w-full max-w-[360px] items-end justify-center overflow-hidden rounded-xl border border-[hsl(var(--border))]/80 bg-gradient-to-b ${accent} shadow-inner`}
      aria-hidden
    >
      <div className="absolute inset-0 opacity-30 bg-[radial-gradient(ellipse_at_center,hsl(var(--primary)/0.25),transparent_70%)]" />
      {runtimeId === 'b601_rs' ? (
        <svg
          viewBox="0 0 120 160"
          className="relative mb-4 h-[140px] w-[100px] text-slate-400/90 drop-shadow-[0_0_20px_hsl(var(--primary)/0.25)]"
          fill="currentColor"
          aria-hidden
        >
          <rect x="52" y="130" width="16" height="18" rx="2" opacity="0.9" />
          <rect x="54" y="108" width="12" height="24" rx="1.5" />
          <rect x="48" y="82" width="24" height="28" rx="2" transform="rotate(-8 60 96)" />
          <rect x="44" y="54" width="32" height="30" rx="2" transform="rotate(12 60 69)" />
          <rect x="50" y="28" width="20" height="28" rx="2" transform="rotate(-5 60 42)" />
          <circle cx="60" cy="18" r="10" opacity="0.85" />
          <rect x="38" y="14" width="8" height="16" rx="1" transform="rotate(-25 42 22)" />
          <rect x="74" y="14" width="8" height="16" rx="1" transform="rotate(25 78 22)" />
        </svg>
      ) : (
        <Icon
          className="relative mb-6 h-20 w-20 text-[hsl(var(--primary))]/75 drop-shadow-[0_0_24px_hsl(var(--primary)/0.35)]"
          strokeWidth={1.25}
        />
      )}
      {runtimeId === 'b601_rs' && (
        <span className="absolute bottom-2 left-0 right-0 text-center text-[10px] text-muted-foreground/80">
          完整 3D 在工作台 Stage 查看
        </span>
      )}
    </div>
  )
}
