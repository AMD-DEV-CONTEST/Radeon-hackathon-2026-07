import { MessageCircleQuestion, Sparkles } from 'lucide-react'
import { Button } from '../ui/button'
import { openCopilot } from '../../lib/copilotAgent'

interface StepGuidePanelProps {
  goal: string
  successSignal: string
  copilotHint: string
  compact?: boolean
  agentActions?: string[]
}

/** Shared panel: goal, success signal, and Copilot agent hooks. */
export function StepGuidePanel({
  goal,
  successSignal,
  copilotHint,
  compact = false,
  agentActions = [],
}: StepGuidePanelProps) {
  return (
    <div
      className={`rounded-lg border border-[hsl(var(--border))]/50 bg-[hsl(var(--muted))]/20 ${
        compact ? 'p-3 space-y-2 text-xs' : 'p-4 space-y-3 text-sm'
      }`}
    >
      <div>
        <p className="text-[10px] font-semibold uppercase tracking-wider text-[hsl(var(--muted-foreground))]">
          目标
        </p>
        <p className="mt-0.5 text-[hsl(var(--foreground))]/90">{goal}</p>
      </div>
      <div>
        <p className="text-[10px] font-semibold uppercase tracking-wider text-emerald-600/80">
          成功标志
        </p>
        <p className="mt-0.5 text-[hsl(var(--foreground))]/90">{successSignal}</p>
      </div>
      <div className="flex flex-wrap gap-2 pt-1 border-t border-[hsl(var(--border))]/30">
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="h-8 text-xs gap-1"
          onClick={() => openCopilot({ tab: 'chat', prefill: copilotHint })}
        >
          <MessageCircleQuestion className="h-3.5 w-3.5" />
          问智能助手
        </Button>
        {agentActions.map((label) => (
          <Button
            key={label}
            type="button"
            size="sm"
            variant="outline"
            className="h-8 text-xs gap-1 border-[hsl(var(--primary))]/40 text-[hsl(var(--primary))]"
            onClick={() => openCopilot({ tab: 'chat', prefill: `帮我${label}` })}
          >
            <Sparkles className="h-3.5 w-3.5" />
            {label}
          </Button>
        ))}
      </div>
    </div>
  )
}
