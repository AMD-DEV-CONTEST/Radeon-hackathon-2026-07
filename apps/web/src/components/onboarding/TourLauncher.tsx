import { Compass, Play } from 'lucide-react'
import { useLocation } from 'react-router-dom'
import { Button } from '../ui/button'
import { TourFlowDiagram } from './TourFlowDiagram'
import { useTourOptional } from './TourProvider'

/** Compact visual strip — one diagram + one button, no wall of text */
export function TourLaunchStrip() {
  const tour = useTourOptional()
  if (!tour) return null

  return (
    <div className="rounded-xl border border-[hsl(var(--primary))]/25 bg-gradient-to-r from-[hsl(var(--primary))]/8 to-transparent overflow-hidden">
      <div className="flex flex-col sm:flex-row sm:items-center gap-3 p-4">
        <div className="flex-1 min-w-0 scale-[0.85] sm:scale-90 origin-left">
          <TourFlowDiagram variant="overview" />
        </div>
        <div className="flex flex-col items-stretch sm:items-end gap-2 shrink-0">
          <Button
            size="lg"
            className="tour-cta-pulse shadow-lg shadow-[hsl(var(--primary))]/20"
            onClick={() => tour.startTour()}
          >
            <Play className="h-4 w-4 fill-current" />
            开始新手引导
          </Button>
          <span className="text-[10px] text-[hsl(var(--muted-foreground))] text-center sm:text-right">
            高亮带你点 · 约 1 分钟
          </span>
        </div>
      </div>
    </div>
  )
}

/** Floating replay button — hidden on Reachy page (page has its own guide). */
export function TourFab() {
  const tour = useTourOptional()
  const location = useLocation()
  if (!tour || tour.active) return null
  if (location.pathname.includes('/reachy_mini')) return null

  return (
    <button
      type="button"
      onClick={() => tour.startTour()}
      className="fixed bottom-20 left-4 z-40 flex items-center gap-2 rounded-full border border-[hsl(var(--primary))]/40 bg-[hsl(var(--card))]/95 backdrop-blur px-4 py-2.5 text-sm font-medium text-[hsl(var(--foreground))] shadow-lg hover:bg-[hsl(var(--primary))]/10 hover:border-[hsl(var(--primary))]/60 transition-all tour-fab-enter"
      title="重新观看新手引导"
    >
      <Compass className="h-4 w-4 text-[hsl(var(--primary))]" />
      新手引导
    </button>
  )
}
