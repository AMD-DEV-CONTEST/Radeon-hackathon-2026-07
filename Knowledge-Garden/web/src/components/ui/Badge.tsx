import type { ReactNode } from "react"
import { cn } from "../../lib/cn"

type Tone = "default" | "success" | "warn" | "danger" | "muted"

const tones: Record<Tone, string> = {
  default: "bg-accent-dim text-accent border-accent/20",
  success: "bg-emerald-50 text-emerald-700 border-emerald-200",
  warn: "bg-amber-50 text-amber-700 border-amber-200",
  danger: "bg-red-50 text-red-700 border-red-200",
  muted: "bg-zinc-100 text-zinc-500 border-zinc-200",
}

export function Badge({ tone = "default", children, className }: {
  tone?: Tone; children: ReactNode; className?: string
}) {
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-medium", tones[tone], className)}>
      {children}
    </span>
  )
}
