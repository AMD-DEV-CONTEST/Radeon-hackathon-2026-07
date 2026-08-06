/**
 * M9.2 — SetupStepCard
 *
 * Shell for every step page. Shows the step number/title, optional subtitle
 * and a footer row with Prev/Next. The body slot is whatever the step
 * component renders (port scanner, camera preview, etc.).
 */
import { ArrowLeft, ArrowRight, CheckCircle2 } from 'lucide-react'
import type { ReactNode } from 'react'
import { Button } from '../ui/button'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '../ui/card'
import { cn } from '../../lib/utils'
import { useSetup } from './SetupProvider'
import type { SetupStepId } from '../../lib/setup-types'
import { StepGuidePanel } from './StepGuidePanel'

function visibleStepId(step: SetupStepId): SetupStepId {
  if (step === 'camera' || step === 'arm') return 'connect'
  if (step === 'train' || step === 'inference') return 'run'
  return step
}

interface SetupStepCardProps {
  stepId: SetupStepId
  title: string
  description?: string
  /** Render custom extras to the right of the title (e.g. status pill). */
  headerExtra?: ReactNode
  children: ReactNode
  /** Disable Next when the step's precondition isn't met yet. */
  nextDisabled?: boolean
  /** Optional custom Next CTA label (default "Next"). */
  nextLabel?: string
  /** Hide the Prev button (step 1). */
  hidePrev?: boolean
  /** Hide the Next button (step 6). */
  hideNext?: boolean
  /** Custom Next handler (otherwise goNext()). */
  onNext?: () => void
}

export function SetupStepCard({
  stepId,
  title,
  description,
  headerExtra,
  children,
  nextDisabled = false,
  nextLabel,
  hidePrev = false,
  hideNext = false,
  onNext,
}: SetupStepCardProps) {
  const { state, stepIndex, steps, goPrev, goNext } = useSetup()
  const done = state.completed[stepId]
  const guide = steps.find((s) => s.id === visibleStepId(stepId))

  const handleNext = () => {
    if (onNext) onNext()
    else goNext()
  }

  return (
    <Card className="bg-[hsl(var(--card))]/60 backdrop-blur">
      <CardHeader className="flex flex-row items-start gap-4 space-y-0">
        <div
          className={cn(
            'flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-sm font-semibold',
            done
              ? 'bg-emerald-500/20 text-emerald-400'
              : 'bg-[hsl(var(--primary))]/15 text-[hsl(var(--primary))]',
          )}
        >
          {done ? <CheckCircle2 className="h-5 w-5" /> : stepIndex + 1}
        </div>
        <div className="flex-1 min-w-0">
          <CardTitle className="text-lg">{title}</CardTitle>
          {description && (
            <CardDescription className="mt-1">{description}</CardDescription>
          )}
        </div>
        {headerExtra && <div className="shrink-0">{headerExtra}</div>}
      </CardHeader>
      <CardContent className="space-y-6">
        {guide && (
          <StepGuidePanel
            goal={guide.goal}
            successSignal={guide.successSignal}
            copilotHint={guide.copilotHint}
          />
        )}
        {children}
      </CardContent>
      <div className="flex items-center justify-between border-t border-[hsl(var(--border))]/50 p-4">
        <div>
          {!hidePrev && stepIndex > 0 && (
            <Button variant="ghost" onClick={goPrev}>
              <ArrowLeft className="h-4 w-4" />
              上一步
            </Button>
          )}
        </div>
        <div className="flex items-center gap-3 text-xs text-[hsl(var(--muted-foreground))]">
          <span>
            第 {stepIndex + 1} / {steps.length} 阶段
          </span>
          {!hideNext && stepIndex < steps.length - 1 && (
            <Button onClick={handleNext} disabled={nextDisabled}>
              {nextLabel ?? '下一步'}
              <ArrowRight className="h-4 w-4" />
            </Button>
          )}
        </div>
      </div>
    </Card>
  )
}
