import { useCallback, useEffect, useRef, useState } from 'react'

const STORAGE_KEY = 'botversex_copilot_pos'
const PANEL_W = 380
const PANEL_H = 560
const MARGIN = 16

function defaultPos() {
  return {
    x: Math.max(MARGIN, window.innerWidth - PANEL_W - MARGIN),
    y: Math.max(MARGIN, window.innerHeight - PANEL_H - MARGIN),
  }
}

function loadPos(): { x: number; y: number } | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as { x: number; y: number }
    if (typeof parsed.x === 'number' && typeof parsed.y === 'number') return parsed
  } catch {
    /* ignore */
  }
  return null
}

function clampPos(x: number, y: number) {
  const maxX = Math.max(MARGIN, window.innerWidth - PANEL_W - MARGIN)
  const maxY = Math.max(MARGIN, window.innerHeight - 120 - MARGIN)
  return {
    x: Math.min(Math.max(MARGIN, x), maxX),
    y: Math.min(Math.max(MARGIN, y), maxY),
  }
}

export function useDraggablePanel(active: boolean) {
  const [pos, setPos] = useState<{ x: number; y: number }>(() => loadPos() ?? defaultPos())
  const dragRef = useRef<{ startX: number; startY: number; origX: number; origY: number } | null>(null)

  useEffect(() => {
    if (!active) return
    setPos((p) => clampPos(p.x, p.y))
  }, [active])

  useEffect(() => {
    const onResize = () => setPos((p) => clampPos(p.x, p.y))
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  const persist = useCallback((p: { x: number; y: number }) => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(p))
    } catch {
      /* ignore */
    }
  }, [])

  const onDragStart = useCallback(
    (e: React.PointerEvent) => {
      if (e.button !== 0) return
      e.preventDefault()
      dragRef.current = { startX: e.clientX, startY: e.clientY, origX: pos.x, origY: pos.y }
      ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
    },
    [pos.x, pos.y],
  )

  const onDragMove = useCallback((e: React.PointerEvent) => {
    const d = dragRef.current
    if (!d) return
    const next = clampPos(
      d.origX + (e.clientX - d.startX),
      d.origY + (e.clientY - d.startY),
    )
    setPos(next)
  }, [])

  const onDragEnd = useCallback(
    (e: React.PointerEvent) => {
      if (!dragRef.current) return
      dragRef.current = null
      ;(e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId)
      setPos((p) => {
        persist(p)
        return p
      })
    },
    [persist],
  )

  const resetPos = useCallback(() => {
    const p = defaultPos()
    setPos(p)
    persist(p)
  }, [persist])

  return { pos, onDragStart, onDragMove, onDragEnd, resetPos }
}
