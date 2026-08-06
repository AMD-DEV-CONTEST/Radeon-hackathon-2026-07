import { useCallback, useEffect, useLayoutEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { ChevronLeft, ChevronRight, X } from 'lucide-react'
import { Button } from '../ui/button'
import {
  stepIndexForId,
  stepsForMode,
  type ReachyGuideContext,
  type ReachyGuideMode,
  type ReachyGuideStep,
} from './reachyMiniTour'

const STORAGE_KEY = 'botversex_reachy_guide_v1'
const PAD = 10

const INTRO_STEPS: ReachyGuideStep[] = []

function useTargetRect(selector: string | undefined, enabled: boolean) {
  const [rect, setRect] = useState<DOMRect | null>(null)
  const measure = useCallback(() => {
    if (!enabled || !selector) {
      setRect(null)
      return
    }
    const el = document.querySelector(selector)
    if (!el) {
      setRect(null)
      return
    }
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

  return rect
}

function SpotlightOverlay({ rect }: { rect: DOMRect }) {
  const vw = window.innerWidth
  const vh = window.innerHeight
  const x = Math.max(0, rect.left - PAD)
  const y = Math.max(0, rect.top - PAD)
  const w = rect.width + PAD * 2
  const h = rect.height + PAD * 2
  const panel = (style: React.CSSProperties) => (
    <div className="fixed z-[9998] bg-black/70 pointer-events-auto" style={style} />
  )
  return (
    <>
      {panel({ left: 0, top: 0, width: vw, height: y })}
      {panel({ left: 0, top: y, width: x, height: h })}
      {panel({ left: x + w, top: y, width: Math.max(0, vw - x - w), height: h })}
      {panel({ left: 0, top: y + h, width: vw, height: Math.max(0, vh - y - h) })}
      <div
        className="fixed z-[9999] pointer-events-none tour-pulse-ring rounded-xl"
        style={{ left: x, top: y, width: w, height: h }}
      />
    </>
  )
}

function GuideCard({
  step,
  stepIndex,
  stepCount,
  goalMet,
  isLast,
  onPrev,
  onNext,
  onFinish,
}: {
  step: ReachyGuideStep
  stepIndex: number
  stepCount: number
  goalMet: boolean
  isLast: boolean
  onPrev: () => void
  onNext: () => void
  onFinish: () => void
}) {
  return (
    <div className="pointer-events-auto rounded-2xl border-2 border-[hsl(var(--primary))]/50 bg-[hsl(var(--card))] shadow-2xl p-4 space-y-3 tour-card-enter max-w-sm w-full">
      <div className="flex justify-center gap-1.5">
        {Array.from({ length: stepCount }).map((_, i) => (
          <div
            key={i}
            className={`h-1 rounded-full transition-all ${
              i <= stepIndex ? 'w-8 bg-[hsl(var(--primary))]' : 'w-4 bg-[hsl(var(--muted))]'
            }`}
          />
        ))}
      </div>
      <h3 className="text-xl font-bold text-center">{step.title}</h3>
      {goalMet && step.whenDone && (
        <p className="text-center text-emerald-400 text-lg">✓</p>
      )}
      <div className="flex items-center justify-between gap-2">
        <Button variant="ghost" size="sm" onClick={onPrev} disabled={stepIndex === 0}>
          <ChevronLeft className="h-4 w-4" />
        </Button>
        <button type="button" onClick={onFinish} className="text-xs text-muted-foreground hover:underline">
          跳过
        </button>
        <Button size="sm" onClick={onNext} className="min-w-[88px]">
          {isLast ? '完成' : '下一步'}
          {!isLast && <ChevronRight className="h-4 w-4" />}
        </Button>
      </div>
    </div>
  )
}

interface Props {
  ctx: ReachyGuideContext
  autoStart?: boolean
  /** Skip intro and jump straight into this mode walkthrough (e.g. browse path). */
  presetMode?: ReachyGuideMode | null
}

export function ReachyMiniGuide({ ctx, autoStart, presetMode }: Props) {
  const [active, setActive] = useState(false)
  const [mode, setMode] = useState<ReachyGuideMode | null>(null)
  const [stepIndex, setStepIndex] = useState(0)

  const flowSteps: ReachyGuideStep[] = useMemo(
    () => (mode ? stepsForMode(mode) : INTRO_STEPS),
    [mode],
  )
  const step = flowSteps[stepIndex]
  const isVisual = step?.kind === 'visual'
  const isSpotlight = step?.kind === 'spotlight' && !!step?.target
  const rect = useTargetRect(step?.target, active && isSpotlight)
  const goalMet = step?.whenDone?.(ctx) ?? false

  const beginGuide = useCallback(
    (opts?: { preset?: ReachyGuideMode; stepId?: string }) => {
      try {
        localStorage.removeItem(STORAGE_KEY)
      } catch {
        /* ignore */
      }
      setActive(true)
      const preset = opts?.preset ?? presetMode ?? null
      if (preset) {
        setMode(preset)
        if (opts?.stepId) {
          setStepIndex(stepIndexForId(preset, opts.stepId))
        } else {
          const filtered = stepsForMode(preset)
          const firstSpotlight = filtered.findIndex((s) => s.kind === 'spotlight')
          setStepIndex(firstSpotlight >= 0 ? firstSpotlight : 0)
        }
      } else {
        setMode(null)
        setStepIndex(0)
      }
    },
    [presetMode],
  )

  const finish = useCallback(() => {
    setActive(false)
    setMode(null)
    setStepIndex(0)
    try {
      localStorage.setItem(STORAGE_KEY, 'done')
    } catch {
      /* ignore */
    }
  }, [])

  const dismissOverlay = useCallback(() => {
    setActive(false)
  }, [])

  useEffect(() => {
    const onStart = (e: Event) => {
      const detail = (e as CustomEvent<{ preset?: ReachyGuideMode; stepId?: string }>).detail ?? {}
      beginGuide({ preset: detail.preset, stepId: detail.stepId })
    }
    window.addEventListener('botversex:start-reachy-guide', onStart)
    return () => window.removeEventListener('botversex:start-reachy-guide', onStart)
  }, [beginGuide])

  useEffect(() => {
    const onDismiss = () => dismissOverlay()
    window.addEventListener('botversex:dismiss-guides', onDismiss)
    return () => window.removeEventListener('botversex:dismiss-guides', onDismiss)
  }, [dismissOverlay])

  useEffect(() => {
    if (!autoStart) return
    if (!presetMode) {
      try {
        if (localStorage.getItem(STORAGE_KEY) === 'done') return
      } catch {
        /* ignore */
      }
    }
    const t = window.setTimeout(() => beginGuide(), 600)
    return () => clearTimeout(t)
  }, [autoStart, beginGuide, presetMode])

  useEffect(() => {
    if (!active || !step?.demo || ctx.hasPlayedMove) return
    if (step.demo === 'play-hello') {
      const t = window.setTimeout(() => {
        window.dispatchEvent(
          new CustomEvent('botversex:reachy-guide-demo', { detail: { action: 'play-hello' } }),
        )
      }, 500)
      return () => clearTimeout(t)
    }
  }, [active, step?.id, step?.demo, ctx.hasPlayedMove])

  useEffect(() => {
    if (!active || !goalMet || !step?.whenDone) return
    const t = window.setTimeout(() => {
      if (stepIndex >= flowSteps.length - 1) finish()
      else setStepIndex((i) => i + 1)
    }, 600)
    return () => clearTimeout(t)
  }, [active, goalMet, step?.whenDone, step?.id, stepIndex, flowSteps.length, finish])

  useEffect(() => {
    if (!active) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') finish()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [active, finish])

  if (!active) {
    return (
      <button
        type="button"
        onClick={() => beginGuide({ preset: presetMode ?? 'virtual' })}
        className="inline-flex items-center gap-1.5 rounded-full border border-[hsl(var(--primary))]/40 bg-[hsl(var(--primary))]/10 px-3 py-1.5 text-xs font-medium text-[hsl(var(--primary))] hover:bg-[hsl(var(--primary))]/15"
      >
        新手引导
      </button>
    )
  }

  if (!step) {
    return null
  }

  const isLast = stepIndex >= flowSteps.length - 1

  const card = (
    <GuideCard
      step={step}
      stepIndex={stepIndex}
      stepCount={flowSteps.length}
      goalMet={goalMet}
      isLast={isLast}
      onPrev={() => setStepIndex((i) => Math.max(0, i - 1))}
      onNext={() => {
        if (isLast) finish()
        else setStepIndex((i) => i + 1)
      }}
      onFinish={finish}
    />
  )

  return createPortal(
    <div className="reachy-guide-root" aria-live="polite">
      {isVisual && (
        <>
          <div className="fixed inset-0 z-[9997] bg-black/70 pointer-events-auto" aria-hidden />
          <div className="fixed inset-0 z-[10000] flex items-center justify-center p-4 pointer-events-none">
            {card}
          </div>
        </>
      )}

      {isSpotlight && rect && <SpotlightOverlay rect={rect} />}
      {isSpotlight && !rect && (
        <div className="fixed inset-0 z-[9997] bg-black/50 pointer-events-none" aria-hidden />
      )}

      {isSpotlight && (
        <div
          className={
            step.id === 'viewer'
              ? 'fixed top-20 left-1/2 -translate-x-1/2 z-[10000] p-2 pointer-events-none'
              : 'fixed inset-x-0 bottom-0 sm:inset-auto sm:bottom-6 sm:left-1/2 sm:-translate-x-1/2 z-[10000] p-4 sm:max-w-md w-full pointer-events-none'
          }
        >
          {card}
        </div>
      )}

      <button
        type="button"
        onClick={finish}
        className="fixed top-4 right-4 z-[10001] p-2 rounded-full bg-[hsl(var(--card))] border shadow-lg"
        aria-label="关闭引导"
      >
        <X className="h-5 w-5" />
      </button>
    </div>,
    document.body,
  )
}
