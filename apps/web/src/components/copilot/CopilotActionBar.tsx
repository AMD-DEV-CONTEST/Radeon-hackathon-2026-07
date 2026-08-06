import { Sparkles } from 'lucide-react'
import { Button } from '../ui/button'
import { executeCopilotAction, type CopilotAction } from '../../lib/copilotAgent'

export function CopilotActionBar({
  actions,
  compact,
}: {
  actions: CopilotAction[]
  compact?: boolean
}) {
  if (!actions.length) return null

  return (
    <div className={`flex flex-wrap gap-1.5 ${compact ? 'mt-2' : 'mt-3'}`}>
      {actions.map((action, i) => (
        <Button
          key={`${action.type}-${i}`}
          type="button"
          size="sm"
          variant="outline"
          className="h-7 text-xs gap-1 border-[hsl(var(--primary))]/40 text-[hsl(var(--primary))] hover:bg-[hsl(var(--primary))]/10"
          onClick={() => void executeCopilotAction(action)}
        >
          <Sparkles className="h-3 w-3" />
          {action.label}
        </Button>
      ))}
    </div>
  )
}
