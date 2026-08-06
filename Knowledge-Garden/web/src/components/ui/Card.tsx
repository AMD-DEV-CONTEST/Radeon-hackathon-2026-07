import type { ReactNode } from "react"
import { cn } from "../../lib/cn"

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <div className={cn("rounded-xl border border-zinc-200 bg-white shadow-sm", className)}>
      {children}
    </div>
  )
}

export function CardHeader({ title, sub, right }: { title: ReactNode; sub?: ReactNode; right?: ReactNode }) {
  return (
    <div className="flex items-start justify-between border-b border-zinc-100 px-5 py-4">
      <div>
        <div className="text-base font-semibold text-ink">{title}</div>
        {sub && <div className="mt-0.5 text-xs text-zinc-500">{sub}</div>}
      </div>
      {right}
    </div>
  )
}

export function CardBody({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn("px-5 py-4", className)}>{children}</div>
}
