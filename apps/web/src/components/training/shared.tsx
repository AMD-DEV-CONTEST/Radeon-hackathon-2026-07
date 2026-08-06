import { Badge } from '../ui/badge'

export function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    queued: 'border-amber-500/40 text-amber-300',
    running: 'border-sky-500/40 text-sky-300 animate-pulse',
    succeeded: 'border-green-500/40 text-green-300',
    failed: 'border-red-500/40 text-red-300',
    cancelled: 'border-muted text-muted-foreground',
  }
  return (
    <Badge variant="outline" className={`font-mono text-[10px] uppercase ${colors[status] ?? ''}`}>
      {status}
    </Badge>
  )
}

export function LossChart({ points }: { points: { epoch: number; loss: number }[] }) {
  if (points.length === 0) {
    return (
      <div className="h-32 rounded border border-dashed flex items-center justify-center text-xs text-muted-foreground">
        等待训练进度…
      </div>
    )
  }
  const losses = points.map((p) => Math.max(1e-12, p.loss))
  const logLosses = losses.map((l) => Math.log10(l))
  const minY = Math.min(...logLosses)
  const maxY = Math.max(...logLosses)
  const rangeY = Math.max(0.1, maxY - minY)
  const W = 400
  const H = 128
  const pad = 16
  const pts = points.map((p, i) => {
    const x = pad + (i / Math.max(1, points.length - 1)) * (W - 2 * pad)
    const y = H - pad - ((Math.log10(Math.max(1e-12, p.loss)) - minY) / rangeY) * (H - 2 * pad)
    return `${x},${y}`
  })
  const path = `M${pts.join(' L')}`
  const last = points[points.length - 1]
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-32 rounded border bg-muted/20">
      <path d={path} fill="none" stroke="hsl(var(--primary))" strokeWidth={1.6} />
      {points.map((p, i) => {
        const x = pad + (i / Math.max(1, points.length - 1)) * (W - 2 * pad)
        const y = H - pad - ((Math.log10(Math.max(1e-12, p.loss)) - minY) / rangeY) * (H - 2 * pad)
        return <circle key={i} cx={x} cy={y} r={2} fill="hsl(var(--primary))" />
      })}
      <text x={W - pad} y={12} textAnchor="end" fontSize={10} fill="hsl(var(--muted-foreground))">
        loss: {last.loss.toExponential(3)}
      </text>
    </svg>
  )
}

export function FormField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wide text-muted-foreground mb-1">{label}</div>
      {children}
    </div>
  )
}

export function NumberIn({
  value,
  setValue,
  min,
  max,
  step,
}: {
  value: number
  setValue: (n: number) => void
  min?: number
  max?: number
  step?: number
}) {
  return (
    <input
      type="number"
      value={value}
      onChange={(e) => {
        const v = Number(e.target.value)
        if (Number.isFinite(v)) setValue(v)
      }}
      min={min}
      max={max}
      step={step}
      className="w-full px-2 py-1.5 rounded border bg-background font-mono text-xs"
    />
  )
}
