import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { ComputedRef, Ref } from 'vue'
import type { TipView } from '@/api/tips'

export interface TipMarkerLayout {
  tipId: string
  x: number
  y: number
  answering: boolean
}

const ANCHOR_ATTRIBUTE = 'data-tip-layout-anchor'

export function useTipMarkerLayout(
  messageBody: Ref<HTMLElement | null>,
  tips: ComputedRef<TipView[]>,
) {
  const tipMarkers = ref<TipMarkerLayout[]>([])
  let markerFrame: number | null = null
  let bodyResizeObserver: ResizeObserver | null = null
  let bodyMutationObserver: MutationObserver | null = null

  function scheduleLayout() {
    void nextTick(() => {
      if (markerFrame !== null) cancelAnimationFrame(markerFrame)
      markerFrame = requestAnimationFrame(() => {
        markerFrame = null
        updateLayout()
      })
    })
  }

  function updateLayout() {
    const body = messageBody.value
    const messageElement = body?.closest('.message-item')
    if (!body || !(messageElement instanceof HTMLElement)) {
      tipMarkers.value = []
      return
    }

    removeStaleAnchors(body, new Set(tips.value.map(tip => tip.tip_id)))
    insertMissingAnchors(body, tips.value)

    const textIndex = renderedTextIndex(body)
    const messageBounds = messageElement.getBoundingClientRect()
    tipMarkers.value = tips.value.flatMap((tip) => {
      const range = tipTextRange(textIndex, tip.selected_text, tip.selection_start, tip.selection_end)
      if (!range) return []
      const anchor = Array.from(range.getClientRects()).find(rectangle => rectangle.width > 0)
      if (!anchor) return []
      return [{
        tipId: tip.tip_id,
        x: anchor.left - messageBounds.left + anchor.width / 2,
        y: anchor.top - messageBounds.top - 3,
        answering: tip.status === 'answering',
      }]
    })
  }

  onMounted(() => {
    const body = messageBody.value
    if (!body) return
    bodyResizeObserver = new ResizeObserver(scheduleLayout)
    bodyResizeObserver.observe(body)
    bodyMutationObserver = new MutationObserver(scheduleLayout)
    bodyMutationObserver.observe(body, { childList: true, subtree: true, characterData: true })
    scheduleLayout()
  })

  watch(tips, scheduleLayout, { deep: true })

  onBeforeUnmount(() => {
    if (markerFrame !== null) cancelAnimationFrame(markerFrame)
    bodyResizeObserver?.disconnect()
    bodyMutationObserver?.disconnect()
    messageBody.value?.querySelectorAll<HTMLElement>(`[${ANCHOR_ATTRIBUTE}]`).forEach(anchor => anchor.remove())
  })

  return { tipMarkers }
}

function removeStaleAnchors(container: HTMLElement, activeTipIds: Set<string>) {
  container.querySelectorAll<HTMLElement>(`[${ANCHOR_ATTRIBUTE}]`).forEach((anchor) => {
    if (!activeTipIds.has(anchor.dataset.tipLayoutAnchor || '')) anchor.remove()
  })
}

function insertMissingAnchors(container: HTMLElement, tips: TipView[]) {
  const existingTipIds = new Set(
    Array.from(container.querySelectorAll<HTMLElement>(`[${ANCHOR_ATTRIBUTE}]`))
      .map(anchor => anchor.dataset.tipLayoutAnchor || ''),
  )
  const textIndex = renderedTextIndex(container)
  const insertions = tips.flatMap((tip) => {
    if (existingTipIds.has(tip.tip_id)) return []
    const range = tipTextRange(textIndex, tip.selected_text, tip.selection_start, tip.selection_end)
    return range ? [{ tipId: tip.tip_id, range }] : []
  })
  insertions.sort((left, right) => (
    right.range.compareBoundaryPoints(Range.START_TO_START, left.range)
  ))
  insertions.forEach(({ tipId, range }) => {
    const anchor = document.createElement('span')
    anchor.className = 'tip-layout-anchor'
    anchor.dataset.tipLayoutAnchor = tipId
    anchor.setAttribute('aria-hidden', 'true')
    const insertionPoint = range.cloneRange()
    insertionPoint.collapse(true)
    insertionPoint.insertNode(anchor)
  })
}

interface RenderedTextIndex {
  text: string
  nodes: Array<{ node: Text; start: number; end: number }>
}

function renderedTextIndex(container: HTMLElement): RenderedTextIndex {
  const nodes: RenderedTextIndex['nodes'] = []
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT)
  let text = ''
  let current = walker.nextNode()
  while (current) {
    const node = current as Text
    const value = node.data
    if (value && !node.parentElement?.closest('[aria-hidden="true"]')) {
      const start = text.length
      text += value
      nodes.push({ node, start, end: text.length })
    }
    current = walker.nextNode()
  }
  return { text, nodes }
}

function tipTextRange(
  index: RenderedTextIndex,
  selectedText: string,
  selectionStart?: number | null,
  selectionEnd?: number | null,
): Range | null {
  const selected = selectedText.trim()
  if (!selected) return null
  const storedStart = typeof selectionStart === 'number' ? selectionStart : -1
  const storedEnd = typeof selectionEnd === 'number' ? selectionEnd : -1
  const storedSelectionMatches = storedStart >= 0
    && storedEnd > storedStart
    && index.text.slice(storedStart, storedEnd).trim() === selected
  const exactStart = index.text.indexOf(selected)
  const normalizedRange = exactStart < 0 ? normalizedTextRange(index.text, selected) : null
  const start = storedSelectionMatches
    ? storedStart
    : exactStart >= 0
      ? exactStart
      : normalizedRange?.start ?? -1
  if (start < 0) return null
  const end = storedSelectionMatches
    ? storedEnd
    : exactStart >= 0
      ? start + selected.length
      : normalizedRange?.end ?? -1
  const startPoint = textPointAt(index.nodes, start, false)
  const endPoint = textPointAt(index.nodes, end, true)
  if (!startPoint || !endPoint) return null
  const range = document.createRange()
  range.setStart(startPoint.node, startPoint.offset)
  range.setEnd(endPoint.node, endPoint.offset)
  return range
}

function normalizedTextRange(text: string, selectedText: string): { start: number; end: number } | null {
  const indexed = normalizedTextIndex(text)
  const selected = selectedText.replace(/\s+/g, ' ').trim()
  if (!selected) return null
  const normalizedStart = indexed.text.indexOf(selected)
  if (normalizedStart < 0) return null
  const normalizedEnd = normalizedStart + selected.length - 1
  const start = indexed.offsets[normalizedStart]
  const lastCharacter = indexed.offsets[normalizedEnd]
  if (start === undefined || lastCharacter === undefined) return null
  return { start, end: lastCharacter + 1 }
}

function normalizedTextIndex(text: string): { text: string; offsets: number[] } {
  let normalized = ''
  const offsets: number[] = []
  for (let index = 0; index < text.length; index += 1) {
    const character = text[index]
    if (/\s/.test(character)) {
      if (!normalized || normalized.endsWith(' ')) continue
      normalized += ' '
      offsets.push(index)
      continue
    }
    normalized += character
    offsets.push(index)
  }
  return { text: normalized, offsets }
}

function textPointAt(
  nodes: RenderedTextIndex['nodes'],
  offset: number,
  preferPrevious: boolean,
): { node: Text; offset: number } | null {
  const entry = nodes.find((item, index) => (
    offset >= item.start
    && (offset < item.end || (preferPrevious && offset === item.end) || index === nodes.length - 1)
  ))
  if (!entry) return null
  return { node: entry.node, offset: Math.max(0, Math.min(offset - entry.start, entry.node.length)) }
}
