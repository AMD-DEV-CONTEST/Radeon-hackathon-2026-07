import { Link } from 'react-router-dom'
import { Check, Loader2, X, AlertCircle, ShieldCheck } from 'lucide-react'
import { Button } from '../ui/button'
import type { PrepareCheck, PrepareCheckStatus } from './types'

function Icon({ status }: { status: PrepareCheckStatus }) {
  if (status === 'ok') return <Check className="h-4 w-4 text-emerald-400" />
  if (status === 'running' || status === 'pending')
    return <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
  if (status === 'block') return <X className="h-4 w-4 text-red-400" />
  return <AlertCircle className="h-4 w-4 text-amber-400" />
}

export function PrepareStep({
  checks,
  running,
  started,
  onStart,
  blockAction,
}: {
  checks: PrepareCheck[]
  running: boolean
  started: boolean
  onStart: () => void
  blockAction?: { label: string; href: string }
}) {
  const blocked = checks.some((c) => c.status === 'block')

  if (!started) {
    return (
      <div className="space-y-4 text-center py-6">
        <ShieldCheck className="h-10 w-10 mx-auto text-muted-foreground/50" />
        <p className="text-sm text-muted-foreground">检查登录、数据集和名额</p>
        <Button size="lg" className="min-w-[180px]" onClick={onStart}>
          开始检查
        </Button>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        {running ? '检查中…' : blocked ? '有未通过项' : '✓ 全部通过'}
      </p>
      <ul className="space-y-2 rounded-lg border bg-muted/20 p-3">
        {checks.map((c) => (
          <li key={c.id} className="flex items-start gap-3 text-sm">
            <span className="mt-0.5">{Icon({ status: c.status })}</span>
            <div className="flex-1 min-w-0">
              <div>{c.label}</div>
              {c.detail && (
                <div className="text-xs text-muted-foreground mt-0.5">{c.detail}</div>
              )}
              {c.actionHref && c.actionLabel && c.status === 'block' && (
                <Link to={c.actionHref} className="text-xs text-primary underline mt-1 inline-block">
                  {c.actionLabel}
                </Link>
              )}
            </div>
          </li>
        ))}
      </ul>
      {blockAction && blocked && (
        <Link to={blockAction.href}>
          <Button variant="outline" className="w-full">
            {blockAction.label}
          </Button>
        </Link>
      )}
    </div>
  )
}
