import { ChevronLeft, ChevronRight } from 'lucide-react'
import { Button } from '../ui/button'

export function WizardFooter({
  showBack,
  onBack,
  showNext,
  nextLabel,
  onNext,
  nextDisabled,
  hint,
}: {
  showBack: boolean
  onBack: () => void
  showNext: boolean
  nextLabel: string
  onNext: () => void
  nextDisabled?: boolean
  hint?: string
}) {
  return (
    <div className="space-y-2 pt-2">
      {hint && (
        <p className="text-xs text-amber-200/90 text-center px-2">{hint}</p>
      )}
      <div className="flex gap-2">
        {showBack && (
          <Button type="button" variant="outline" size="lg" className="shrink-0" onClick={onBack}>
            <ChevronLeft className="h-4 w-4 mr-1" />
            上一步
          </Button>
        )}
        {showNext && (
          <Button
            type="button"
            size="lg"
            className="flex-1"
            onClick={onNext}
            disabled={nextDisabled}
          >
            {nextLabel}
            <ChevronRight className="h-4 w-4 ml-1" />
          </Button>
        )}
      </div>
    </div>
  )
}
