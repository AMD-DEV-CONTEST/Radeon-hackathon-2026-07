/**
 * M9.2 — SetupSidebar
 *
 * Vertical stepper that lives to the left of the wizard. Each row shows:
 *   - step index in a circle (green when complete, primary when active, muted otherwise)
 *   - label + short hint
 *   - a lock icon if the user hasn't satisfied the jump precondition
 *
 * Rules are delegated to the provider (`canJumpTo`) so future runtimes can
 * ship their own gating without touching this component.
 */
import { Check, Lock } from 'lucide-react'
import { cn } from '../../lib/utils'
import type { SetupStepId } from '../../lib/setup-types'
import { useSetup } from './SetupProvider'

function visibleStepId(step: SetupStepId): SetupStepId {
  if (step === 'camera' || step === 'arm') return 'connect'
  if (step === 'train' || step === 'inference') return 'run'
  return step
}

export function SetupSidebar() {
  const { state, steps, goTo, canJumpTo } = useSetup()
  const activeGuide = steps.find((s) => s.id === visibleStepId(state.currentStep))
  const sidebarTitle =
    state.runtimeId === 'b601_rs' ? 'B601-RS 引导' : 'SO-101 引导'

  return (
    <aside className="w-full md:w-64 shrink-0">
      <div className="rounded-xl border border-[hsl(var(--border))]/60 bg-[hsl(var(--card))]/40 p-3 space-y-1">
        <div className="px-2 py-1 text-xs font-semibold uppercase tracking-wider text-[hsl(var(--muted-foreground))]">
          {sidebarTitle}
        </div>
        {steps.map((step) => {
          const isActive = state.currentStep === step.id
          const isDone = state.completed[step.id]
          const allowed = canJumpTo(step.id)
          return (
            <button
              key={step.id}
              type="button"
              disabled={!allowed}
              onClick={() => allowed && goTo(step.id)}
              className={cn(
                'w-full flex items-start gap-3 rounded-lg px-3 py-2 text-left transition-colors',
                isActive
                  ? 'bg-[hsl(var(--primary))]/15 text-[hsl(var(--foreground))]'
                  : 'hover:bg-[hsl(var(--muted))] text-[hsl(var(--muted-foreground))]',
                !allowed && 'opacity-50 cursor-not-allowed hover:bg-transparent',
              )}
            >
              <span
                className={cn(
                  'mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold',
                  isDone
                    ? 'bg-emerald-500/20 text-emerald-400 ring-1 ring-emerald-500/40'
                    : isActive
                      ? 'bg-[hsl(var(--primary))]/20 text-[hsl(var(--primary))] ring-1 ring-[hsl(var(--primary))]/40'
                      : 'bg-[hsl(var(--muted))] text-[hsl(var(--muted-foreground))]',
                )}
              >
                {isDone ? <Check className="h-3.5 w-3.5" /> : step.index + 1}
              </span>
              <span className="min-w-0 flex-1">
                <span className="flex items-center gap-1.5">
                  <span
                    className={cn(
                      'text-sm font-medium truncate',
                      isActive && 'text-[hsl(var(--foreground))]',
                    )}
                  >
                    {step.label}
                  </span>
                  {!allowed && <Lock className="h-3 w-3 opacity-60" />}
                </span>
                <span className="block text-[11px] leading-tight mt-0.5 text-[hsl(var(--muted-foreground))] truncate">
                  {step.shortHint}
                </span>
              </span>
            </button>
          )
        })}
        {activeGuide && (
          <div className="mt-3 mx-2 pt-3 border-t border-[hsl(var(--border))]/40 space-y-1.5 text-[11px]">
            <p className="text-[hsl(var(--muted-foreground))]">
              <span className="font-medium text-[hsl(var(--foreground))]/80">目标：</span>
              {activeGuide.goal}
            </p>
            <p className="text-emerald-600/80">
              <span className="font-medium">成功：</span>
              {activeGuide.successSignal}
            </p>
          </div>
        )}
      </div>
    </aside>
  )
}
