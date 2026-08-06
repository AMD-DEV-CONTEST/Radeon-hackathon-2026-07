/**
 * M9.2 — Dashboard setup checklist card
 *
 * A lightweight "is this box ready?" widget that surfaces the aggregated
 * /api/v1/setup/status output: overall traffic light + top 2 actionable
 * issues + a CTA back into the runtime wizard. Meant to be dropped onto
 * the Dashboard so new users see it the moment they log in.
 */
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Loader2,
  ShieldAlert,
} from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '../ui/card'
import { buttonVariants } from '../ui/button'
import { cn } from '../../lib/utils'
import type { SetupStatus } from '../../lib/setup-types'

export function SetupChecklistCard() {
  const [status, setStatus] = useState<SetupStatus | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    void (async () => {
      try {
        // /api/v1/setup/status is unauthenticated by design (M9.1).
        const r = await fetch('/api/v1/setup/status')
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        setStatus((await r.json()) as SetupStatus)
      } catch (e) {
        setErr((e as Error).message)
      }
    })()
  }, [])

  const overall = status?.overall
  const tone =
    overall === 'ok'
      ? 'emerald'
      : overall === 'warning'
        ? 'amber'
        : overall === 'error'
          ? 'red'
          : 'muted'

  const Icon =
    overall === 'ok' ? CheckCircle2 : overall === 'error' ? ShieldAlert : AlertTriangle

  const targetPath = status?.next_action?.path ?? '/robots/so101'
  const targetLabel = status?.next_action?.label ?? 'Open SO-101 setup'

  return (
    <Card className="bg-[hsl(var(--card))]/60">
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <Icon
            className={cn(
              'h-5 w-5',
              tone === 'emerald' && 'text-emerald-400',
              tone === 'amber' && 'text-amber-400',
              tone === 'red' && 'text-red-400',
              tone === 'muted' && 'text-[hsl(var(--muted-foreground))]',
            )}
          />
          Setup readiness
        </CardTitle>
        <span
          className={cn(
            'rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider',
            tone === 'emerald' && 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300',
            tone === 'amber' && 'border-amber-500/40 bg-amber-500/10 text-amber-300',
            tone === 'red' && 'border-red-500/40 bg-red-500/10 text-red-300',
            tone === 'muted' && 'border-[hsl(var(--border))] text-[hsl(var(--muted-foreground))]',
          )}
        >
          {overall ?? '—'}
        </span>
      </CardHeader>
      <CardContent className="space-y-3">
        {!status && !err && (
          <div className="flex items-center gap-2 text-sm text-[hsl(var(--muted-foreground))]">
            <Loader2 className="h-4 w-4 animate-spin" />
            Checking hardware + services…
          </div>
        )}
        {err && (
          <div className="rounded-md border border-red-500/30 bg-red-500/5 p-2.5 text-xs text-red-300">
            Couldn't reach /api/v1/setup/status: {err}
          </div>
        )}
        {status && (
          <>
            {status.issues.length === 0 ? (
              <p className="text-sm text-[hsl(var(--muted-foreground))]">
                All checks passed. Your platform is ready to record, train and run inference.
              </p>
            ) : (
              <ul className="space-y-1.5 text-xs">
                {status.issues.slice(0, 3).map((iss, i) => (
                  <li key={i} className="flex items-start gap-2">
                    <span
                      className={cn(
                        'mt-0.5 inline-block h-1.5 w-1.5 shrink-0 rounded-full',
                        iss.severity === 'error' && 'bg-red-400',
                        iss.severity === 'warning' && 'bg-amber-400',
                        iss.severity === 'info' && 'bg-sky-400',
                      )}
                    />
                    <span className="text-[hsl(var(--muted-foreground))]">{iss.message}</span>
                  </li>
                ))}
                {status.issues.length > 3 && (
                  <li className="text-[11px] text-[hsl(var(--muted-foreground))]/70 pl-3.5">
                    + {status.issues.length - 3} more
                  </li>
                )}
              </ul>
            )}

            <Link
              to={targetPath}
              className={buttonVariants({ variant: 'default', size: 'sm' }) + ' w-full'}
            >
              {targetLabel}
              <ArrowRight className="h-4 w-4" />
            </Link>
          </>
        )}
      </CardContent>
    </Card>
  )
}
