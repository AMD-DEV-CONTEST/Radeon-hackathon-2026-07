import { useCallback, useLayoutEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { Bot, ChevronLeft, ChevronRight, Monitor, X } from 'lucide-react'
import { Button } from '../ui/button'
import { TourFlowDiagram } from './TourFlowDiagram'
import { useTour } from './TourProvider'
import type { TourStep } from './tours'

const PAD = 10
const TOOLTIP_GAP = 14

function useTargetRect(selector: string | undefined, enabled: boolean) {
  const [rect, setRect] = useState<DOMRect | null>(null)
  const [missing, setMissing] = useState(false)

  const measure = useCallback(() => {
    if (!enabled || !selector) {
      setRect(null)
      setMissing(false)
      return
    }
    const el = document.querySelector(selector)
    if (!el) {
      setRect(null)
      setMissing(true)
      return
    }
    setMissing(false)
    el.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
    setRect(el.getBoundingClientRect())
  }, [selector, enabled])

  useLayoutEffect(() => {
    measure()
    if (!enabled) return
    const id = window.setInterval(measure, 400)
    window.addEventListener('resize', measure)
    window.addEventListener('scroll', measure, true)
    return () => {
      clearInterval(id)
      window.removeEventListener('resize', measure)
      window.removeEventListener('scroll', measure, true)
    }
  }, [measure, enabled])

  return { rect, missing }
}

function tooltipStyle(rect: DOMRect, placement: TourStep['placement']): React.CSSProperties {
  const vw = window.innerWidth
  const vh = window.innerHeight
  const w = Math.min(320, vw - 24)
  let top = rect.bottom + TOOLTIP_GAP
  let left = rect.left + rect.width / 2 - w / 2

  if (placement === 'top') top = rect.top - TOOLTIP_GAP - 160
  else if (placement === 'left') {
    top = rect.top + rect.height / 2 - 80
    left = rect.left - w - TOOLTIP_GAP
  } else if (placement === 'right') {
    top = rect.top + rect.height / 2 - 80
    left = rect.right + TOOLTIP_GAP
  }

  left = Math.max(12, Math.min(left, vw - w - 12))
  top = Math.max(12, Math.min(top, vh - 180))
  return { position: 'fixed', top, left, width: w, zIndex: 10002 }
}

function OverlayPanels({ rect }: { rect: DOMRect }) {
  const vw = window.innerWidth
  const vh = window.innerHeight
  const x = Math.max(0, rect.left - PAD)
  const y = Math.max(0, rect.top - PAD)
  const w = rect.width + PAD * 2
  const h = rect.height + PAD * 2
  const panel = (style: React.CSSProperties) => (
    <div className="fixed z-[9999] bg-black/78 pointer-events-auto tour-overlay-fade" style={style} />
  )
  return (
    <>
      {panel({ left: 0, top: 0, width: vw, height: y })}
      {panel({ left: 0, top: y, width: x, height: h })}
      {panel({ left: x + w, top: y, width: Math.max(0, vw - x - w), height: h })}
      {panel({ left: 0, top: y + h, width: vw, height: Math.max(0, vh - y - h) })}
      <div
        className="fixed z-[10001] pointer-events-none tour-pulse-ring"
        style={{ left: x, top: y, width: w, height: h, borderRadius: 12 }}
      />
    </>
  )
}

function VisualStep({ step }: { step: TourStep }) {
  return (
    <>
      <div className="fixed inset-0 z-[9999] bg-black/78 pointer-events-auto" aria-hidden />
      <div className="fixed inset-0 z-[10001] flex items-center justify-center p-4 pointer-events-none">
        <div className="pointer-events-auto w-full max-w-lg rounded-2xl border border-[hsl(var(--primary))]/30 bg-[hsl(var(--card))] shadow-2xl tour-card-enter p-6 space-y-4">
          {step.visual && <TourFlowDiagram variant={step.visual} />}
          <div className="text-center space-y-1">
            <h3 className="text-lg font-bold">{step.title}</h3>
            <p className="text-sm text-[hsl(var(--muted-foreground))]">{step.caption}</p>
          </div>
        </div>
      </div>
    </>
  )
}

function ChoiceStep({
  step,
  stepIndex,
  stepCount,
  onChoose,
  onSkip,
}: {
  step: TourStep
  stepIndex: number
  stepCount: number
  onChoose: (path: 'hardware' | 'browse') => void
  onSkip: () => void
}) {
  return (
    <>
      <div className="fixed inset-0 z-[9999] bg-black/78 pointer-events-auto" aria-hidden />
      <div className="fixed inset-0 z-[10001] flex items-center justify-center p-4 pointer-events-none">
        <div className="pointer-events-auto w-full max-w-md rounded-2xl border border-[hsl(var(--primary))]/30 bg-[hsl(var(--card))] shadow-2xl tour-card-enter p-6 space-y-4">
          <div className="flex justify-between items-start">
            <div>
              <p className="text-[10px] uppercase tracking-wider text-[hsl(var(--primary))] font-semibold">
                引导 {stepIndex + 1}/{stepCount}
              </p>
              <h3 className="text-lg font-bold mt-1">{step.title}</h3>
              <p className="text-sm text-[hsl(var(--muted-foreground))]">{step.caption}</p>
            </div>
            <button type="button" onClick={onSkip} className="p-1 text-muted-foreground hover:text-foreground">
              <X className="h-4 w-4" />
            </button>
          </div>
          <div className="grid gap-3">
            <button
              type="button"
              onClick={() => onChoose('hardware')}
              className="flex items-center gap-3 rounded-xl border-2 border-[hsl(var(--primary))]/50 bg-[hsl(var(--primary))]/10 p-4 text-left hover:bg-[hsl(var(--primary))]/15 transition-colors"
            >
              <Bot className="h-8 w-8 text-[hsl(var(--primary))] shrink-0" />
              <div>
                <div className="font-semibold">A · 我有机械臂</div>
                <div className="text-xs text-[hsl(var(--muted-foreground))] mt-0.5">
                  Setup 装 Agent → 进入 SO-101 向导
                </div>
              </div>
            </button>
            <button
              type="button"
              onClick={() => onChoose('browse')}
              className="flex items-center gap-3 rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--muted))]/20 p-4 text-left hover:bg-[hsl(var(--muted))]/40 transition-colors"
            >
              <Monitor className="h-8 w-8 text-[hsl(var(--muted-foreground))] shrink-0" />
              <div>
                <div className="font-semibold">B · 我没有机械臂</div>
                <div className="text-xs text-[hsl(var(--muted-foreground))] mt-0.5">
                  Reachy 虚拟模式 / 先逛逛
                </div>
              </div>
            </button>
          </div>
        </div>
      </div>
    </>
  )
}

function TooltipCard({
  step,
  stepIndex,
  stepCount,
  style,
  onPrev,
  onNext,
  onSkip,
  isLast,
}: {
  step: TourStep
  stepIndex: number
  stepCount: number
  style: React.CSSProperties
  onPrev: () => void
  onNext: () => void
  onSkip: () => void
  isLast: boolean
}) {
  return (
    <div
      style={style}
      className="rounded-xl border border-[hsl(var(--primary))]/40 bg-[hsl(var(--card))] shadow-xl tour-card-enter p-4 space-y-3"
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="text-[10px] uppercase tracking-wider text-[hsl(var(--primary))] font-semibold mb-0.5">
            引导 {stepIndex + 1}/{stepCount}
          </div>
          <h3 className="text-base font-bold">{step.title}</h3>
          <p className="text-sm text-[hsl(var(--muted-foreground))] mt-1">{step.caption}</p>
          {step.hint && (
            <p className="text-xs text-[hsl(var(--primary))] mt-2 border-t border-[hsl(var(--border))]/50 pt-2">
              → {step.hint}
            </p>
          )}
        </div>
        <button type="button" onClick={onSkip} className="shrink-0 p-1 rounded-md text-muted-foreground hover:text-foreground">
          <X className="h-4 w-4" />
        </button>
      </div>
      <div className="flex gap-1.5">
        {Array.from({ length: stepCount }).map((_, i) => (
          <div
            key={i}
            className={`h-1 flex-1 rounded-full ${i <= stepIndex ? 'bg-[hsl(var(--primary))]' : 'bg-[hsl(var(--muted))]'}`}
          />
        ))}
      </div>
      <div className="flex justify-between gap-2 pt-1">
        <Button variant="ghost" size="sm" onClick={onPrev} disabled={stepIndex === 0}>
          <ChevronLeft className="h-4 w-4" />
          上一步
        </Button>
        <Button size="sm" onClick={onNext} className="min-w-[100px]">
          {isLast ? '完成' : '下一步'}
          {!isLast && <ChevronRight className="h-4 w-4" />}
        </Button>
      </div>
    </div>
  )
}

export function ProductTour() {
  const { active, currentStep, stepIndex, stepCount, next, prev, skip, choosePath } = useTour()
  const step = currentStep
  const isChoice = step?.kind === 'choice'
  const isVisual = step?.kind === 'visual'
  const isSpotlight = step?.kind === 'spotlight' || (!!step?.target && !isChoice && !isVisual)
  const { rect, missing } = useTargetRect(step?.target, active && isSpotlight && !!step)

  if (!active || !step) return null

  const isLast = stepIndex >= stepCount - 1
  const tooltipPos = rect && isSpotlight ? tooltipStyle(rect, step.placement ?? 'bottom') : null

  return createPortal(
    <div className="tour-root" aria-live="polite">
      {isChoice && (
        <ChoiceStep
          step={step}
          stepIndex={stepIndex}
          stepCount={stepCount}
          onChoose={choosePath}
          onSkip={skip}
        />
      )}
      {isVisual && <VisualStep step={step} />}
      {isSpotlight && rect && <OverlayPanels rect={rect} />}
      {isVisual && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-[10003] flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={prev} disabled={stepIndex === 0} className="bg-[hsl(var(--card))]/90">
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <Button size="sm" onClick={next} className="min-w-[120px] shadow-lg">
            {isLast ? '开始探索' : '下一步'}
            {!isLast && <ChevronRight className="h-4 w-4" />}
          </Button>
          <button type="button" onClick={skip} className="text-xs text-muted-foreground hover:underline px-2">
            跳过
          </button>
        </div>
      )}
      {isSpotlight && tooltipPos && (
        <TooltipCard
          step={step}
          stepIndex={stepIndex}
          stepCount={stepCount}
          style={tooltipPos}
          onPrev={prev}
          onNext={next}
          onSkip={skip}
          isLast={isLast}
        />
      )}
      {isSpotlight && missing && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-[10003] rounded-lg bg-[hsl(var(--card))] border px-4 py-2 text-sm text-muted-foreground">
          正在加载页面…
        </div>
      )}
    </div>,
    document.body,
  )
}
