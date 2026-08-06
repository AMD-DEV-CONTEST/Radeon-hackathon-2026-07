import { Check, Circle } from 'lucide-react'
import type { WizardStep } from './types'

const STEPS: { id: WizardStep; label: string }[] = [
  { id: 'data', label: '选数据' },
  { id: 'goal', label: '训练方式' },
  { id: 'prepare', label: '自动准备' },
  { id: 'confirm', label: '开始训练' },
]

function stepIndex(s: WizardStep): number {
  if (s === 'running' || s === 'done') return 4
  const i = STEPS.findIndex((x) => x.id === s)
  return i >= 0 ? i : 0
}

export function WizardProgress({
  step,
  onJump,
}: {
  step: WizardStep
  onJump?: (target: WizardStep) => void
}) {
  const current = stepIndex(step)
  const donePhase = step === 'running' || step === 'done'

  return (
    <div className="flex flex-wrap items-center gap-2 md:gap-4">
      {STEPS.map((s, i) => {
        const done = donePhase || i < current
        const active = !donePhase && i === current
        const canJump = Boolean(onJump && done && !donePhase && s.id !== step)
        return (
          <div key={s.id} className="flex items-center gap-2">
            <button
              type="button"
              disabled={!canJump}
              onClick={() => canJump && onJump?.(s.id)}
              className={`flex h-8 w-8 items-center justify-center rounded-full border text-xs font-semibold transition-colors ${
                done
                  ? 'border-emerald-500/50 bg-emerald-500/15 text-emerald-400'
                  : active
                    ? 'border-primary bg-primary/15 text-primary'
                    : 'border-muted text-muted-foreground'
              } ${canJump ? 'cursor-pointer hover:ring-2 hover:ring-primary/30' : 'cursor-default'}`}
              title={canJump ? `返回：${s.label}` : undefined}
            >
              {done ? <Check className="h-4 w-4" /> : i + 1}
            </button>
            <button
              type="button"
              disabled={!canJump}
              onClick={() => canJump && onJump?.(s.id)}
              className={`text-sm text-left ${active ? 'font-medium text-foreground' : 'text-muted-foreground'} ${
                canJump ? 'hover:text-foreground underline-offset-2 hover:underline cursor-pointer' : 'cursor-default'
              }`}
            >
              {s.label}
            </button>
            {i < STEPS.length - 1 && (
              <Circle className="h-1 w-1 fill-muted-foreground/40 text-transparent mx-1 hidden sm:block" />
            )}
          </div>
        )
      })}
      {donePhase && (
        <span className="text-sm text-sky-300 ml-2">
          {step === 'done' ? '· 训练完成' : '· 训练中'}
        </span>
      )}
    </div>
  )
}
