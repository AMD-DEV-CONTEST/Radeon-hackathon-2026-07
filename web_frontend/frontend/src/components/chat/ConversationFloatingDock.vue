<template>
  <div ref="layerRef" class="floating-dock-layer">
    <div
      v-if="draggingId"
      class="snap-guide"
      :class="`guide-${previewSide}`"
      aria-hidden="true"
    ></div>

    <div
      v-for="item in floatingItems"
      :key="item.id"
      :ref="element => setItemElement(item.id, element)"
      class="floating-dock-item"
      :class="[
        `floating-${item.id}`,
        `side-${position(item.id).side}`,
        { 'is-dragging': draggingId === item.id },
      ]"
      :style="itemStyle(item.id)"
      @pointerdown="startDrag(item.id, $event)"
      @click.capture="captureClick"
    >
      <n-popover
        v-if="item.id === 'sessions'"
        trigger="click"
        :show="uiStore.conversationDockPanel === 'sessions'"
        :placement="panelPlacement(item.id)"
        :show-arrow="false"
        raw
        @update:show="setPanelVisibility('sessions', $event)"
      >
        <template #trigger>
          <button class="dock-capsule" type="button">
            <n-icon size="15"><ChatbubblesOutline /></n-icon>
            <span>{{ t('right.sessions') }}</span>
          </button>
        </template>
        <div class="dock-panel session-panel-shell">
          <SessionsSidebarPanel @request-new-agent-session="forwardNewAgentSessionRequest" />
        </div>
      </n-popover>

      <n-popover
        v-else-if="item.id === 'workspace'"
        trigger="click"
        :show="uiStore.conversationDockPanel === 'workspace'"
        :placement="panelPlacement(item.id)"
        :show-arrow="false"
        raw
        @update:show="setPanelVisibility('workspace', $event)"
      >
        <template #trigger>
          <button class="dock-card" type="button">
            <n-icon size="16"><FolderOpenOutline /></n-icon>
            <span>{{ t('right.workspace') }}</span>
          </button>
        </template>
        <div class="dock-panel workspace-panel-shell"><WorkspaceSidebarPanel /></div>
      </n-popover>

      <n-popover
        v-else-if="item.id === 'memory'"
        trigger="click"
        :show="uiStore.conversationDockPanel === 'memory'"
        :placement="panelPlacement(item.id)"
        :show-arrow="false"
        raw
        @update:show="setPanelVisibility('memory', $event)"
      >
        <template #trigger>
          <button class="dock-card" type="button">
            <n-icon size="16"><SparklesOutline /></n-icon>
            <span>{{ t('status.memory') }}</span>
          </button>
        </template>
        <div class="dock-panel"><ConversationMemoryPanel /></div>
      </n-popover>

      <BackgroundTaskStack
        v-else
        :ref="setTaskStackRef"
        :session-id="sessionId"
        compact
        :side="position(item.id).side"
      />
    </div>

  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import type { ComponentPublicInstance, CSSProperties } from 'vue'
import { NIcon, NPopover } from 'naive-ui'
import { ChatbubblesOutline, FolderOpenOutline, SparklesOutline } from '@/components/icons'
import { useI18n } from '@/composables/useI18n'
import { useUiStore, type ConversationDockPanel } from '@/stores/ui'
import SessionsSidebarPanel from '@/components/common/right-sidebar/SessionsSidebarPanel.vue'
import WorkspaceSidebarPanel from '@/components/common/right-sidebar/WorkspaceSidebarPanel.vue'
import ConversationMemoryPanel from './ConversationMemoryPanel.vue'
import BackgroundTaskStack from './BackgroundTaskStack.vue'

type FloatingItemId = 'sessions' | 'workspace' | 'memory' | 'tasks'
type DockSide = 'left' | 'right'
interface DockPosition { side: DockSide; y: number }
interface DragState {
  id: FloatingItemId
  pointerId: number
  offsetX: number
  offsetY: number
  x: number
  y: number
  originClientX: number
  originClientY: number
  moved: boolean
}
interface TaskStackInstance { syncPosition: () => void }

defineProps<{ sessionId?: string | null }>()
const emit = defineEmits<{
  requestNewAgentSession: [packageId: string, initialWorkspaceId: string | null]
}>()
const { t } = useI18n()
const uiStore = useUiStore()
const layerRef = ref<HTMLElement | null>(null)
const taskStackRef = ref<TaskStackInstance | null>(null)
const itemElements = new Map<FloatingItemId, HTMLElement>()
const dragging = ref<DragState | null>(null)
const suppressNextClick = ref(false)
const positions = ref<Record<FloatingItemId, DockPosition>>(loadPositions())
let taskPanelSyncFrame: number | null = null
const floatingItems: Array<{ id: FloatingItemId }> = [
  { id: 'sessions' },
  { id: 'workspace' },
  { id: 'memory' },
  { id: 'tasks' },
]
const draggingId = computed(() => dragging.value?.id || null)
const previewSide = computed<DockSide>(() => {
  const state = dragging.value
  const layer = layerRef.value
  if (!state || !layer) return 'left'
  return state.x + itemWidth(state.id) / 2 < layer.clientWidth / 2 ? 'left' : 'right'
})

function defaultPositions(): Record<FloatingItemId, DockPosition> {
  return {
    sessions: { side: 'left', y: 0.23 },
    workspace: { side: 'left', y: 0.38 },
    memory: { side: 'left', y: 0.47 },
    tasks: { side: 'right', y: 0.7 },
  }
}

function loadPositions(): Record<FloatingItemId, DockPosition> {
  const defaults = defaultPositions()
  if (typeof window === 'undefined') return defaults
  try {
    const value = JSON.parse(window.localStorage.getItem('fast-agent-factory.floatingDockPositions') || '{}')
    for (const id of Object.keys(defaults) as FloatingItemId[]) {
      const candidate = value?.[id]
      if ((candidate?.side === 'left' || candidate?.side === 'right') && Number.isFinite(candidate?.y)) {
        defaults[id] = { side: candidate.side, y: clamp(Number(candidate.y), 0, 1) }
      }
    }
  } catch {
    return defaults
  }
  return defaults
}

function savePositions() {
  window.localStorage.setItem('fast-agent-factory.floatingDockPositions', JSON.stringify(positions.value))
}

function position(id: FloatingItemId): DockPosition {
  return positions.value[id]
}

function itemStyle(id: FloatingItemId): CSSProperties {
  const state = dragging.value
  if (state?.id === id) {
    return { left: `${state.x}px`, right: 'auto', top: `${state.y}px` }
  }
  const item = itemElements.get(id)
  const layer = layerRef.value
  const availableHeight = Math.max(0, (layer?.clientHeight || 0) - (item?.offsetHeight || 0) - 16)
  return { top: `${8 + availableHeight * position(id).y}px` }
}

function panelPlacement(id: FloatingItemId) {
  return position(id).side === 'left' ? 'right-start' : 'left-start'
}

function setPanelVisibility(panel: ConversationDockPanel, visible: boolean) {
  if (suppressNextClick.value) return
  uiStore.setConversationDockPanel(visible ? panel : null)
}

function forwardNewAgentSessionRequest(packageId: string, initialWorkspaceId: string | null) {
  uiStore.setConversationDockPanel(null)
  emit('requestNewAgentSession', packageId, initialWorkspaceId)
}

function setItemElement(id: FloatingItemId, value: Element | ComponentPublicInstance | null) {
  const element = value instanceof HTMLElement
    ? value
    : value && '$el' in value && value.$el instanceof HTMLElement
      ? value.$el
      : null
  if (element) itemElements.set(id, element)
  else itemElements.delete(id)
}

function setTaskStackRef(value: Element | ComponentPublicInstance | null) {
  taskStackRef.value = value && 'syncPosition' in value
    ? value as unknown as TaskStackInstance
    : null
}

function startDrag(id: FloatingItemId, event: PointerEvent) {
  if (event.button !== 0 || !layerRef.value) return
  if ((event.target as HTMLElement).closest('.task-stack-list')) return
  const element = itemElements.get(id)
  if (!element) return
  const layerRect = layerRef.value.getBoundingClientRect()
  const itemRect = element.getBoundingClientRect()
  dragging.value = {
    id,
    pointerId: event.pointerId,
    offsetX: event.clientX - itemRect.left,
    offsetY: event.clientY - itemRect.top,
    x: itemRect.left - layerRect.left,
    y: itemRect.top - layerRect.top,
    originClientX: event.clientX,
    originClientY: event.clientY,
    moved: false,
  }
  window.addEventListener('pointermove', handleDrag)
  window.addEventListener('pointerup', finishDrag)
  window.addEventListener('pointercancel', finishDrag)
}

function handleDrag(event: PointerEvent) {
  const state = dragging.value
  const layer = layerRef.value
  if (!state || !layer || event.pointerId !== state.pointerId) return
  const bounds = layer.getBoundingClientRect()
  const width = itemWidth(state.id)
  const height = itemHeight(state.id)
  const nextX = clamp(event.clientX - bounds.left - state.offsetX, 8, Math.max(8, bounds.width - width - 8))
  const nextY = clamp(event.clientY - bounds.top - state.offsetY, 8, Math.max(8, bounds.height - height - 8))
  if (Math.hypot(event.clientX - state.originClientX, event.clientY - state.originClientY) > 5) state.moved = true
  state.x = nextX
  state.y = nextY
  dragging.value = { ...state }
  scheduleTaskPanelSync(state.id)
}

function finishDrag(event: PointerEvent) {
  const state = dragging.value
  const layer = layerRef.value
  if (!state || !layer || event.pointerId !== state.pointerId) return
  stopDragListeners()
  if (!state.moved) {
    dragging.value = null
    return
  }
  event.preventDefault()
  suppressNextClick.value = true
  uiStore.setConversationDockPanel(null)
  const element = itemElements.get(state.id)
  const currentRect = element?.getBoundingClientRect()
  const layerRect = layer.getBoundingClientRect()
  const side = state.x + itemWidth(state.id) / 2 < layer.clientWidth / 2 ? 'left' : 'right'
  const availableHeight = Math.max(1, layer.clientHeight - itemHeight(state.id) - 16)
  positions.value = {
    ...positions.value,
    [state.id]: { side, y: clamp((state.y - 8) / availableHeight, 0, 1) },
  }
  savePositions()
  dragging.value = null
  void nextTick(() => animateSnap(state.id, element, currentRect, layerRect, side))
  window.setTimeout(() => { suppressNextClick.value = false }, 160)
}

function animateSnap(
  id: FloatingItemId,
  element: HTMLElement | undefined,
  from: DOMRect | undefined,
  layerRect: DOMRect,
  side: DockSide,
) {
  if (!element || !from) return
  const target = element.getBoundingClientRect()
  const edgeDistance = side === 'left'
    ? Math.max(0, from.left - layerRect.left)
    : Math.max(0, layerRect.right - from.right)
  const animation = element.animate(
    [
      { transform: `translate3d(${from.left - target.left}px, ${from.top - target.top}px, 0) scale(1.035)` },
      { transform: `translate3d(${(from.left - target.left) * 0.12}px, ${(from.top - target.top) * 0.12}px, 0) scale(${edgeDistance < 70 ? 0.985 : 1})`, offset: .78 },
      { transform: 'translate3d(0, 0, 0) scale(1)' },
    ],
    { duration: 440, easing: 'cubic-bezier(.16, 1, .3, 1)' },
  )
  trackTaskPanelAnimation(id, animation)
}

function scheduleTaskPanelSync(id: FloatingItemId) {
  if (id !== 'tasks' || taskPanelSyncFrame !== null) return
  taskPanelSyncFrame = window.requestAnimationFrame(() => {
    taskPanelSyncFrame = null
    void nextTick(() => taskStackRef.value?.syncPosition())
  })
}

function trackTaskPanelAnimation(id: FloatingItemId, animation: Animation) {
  if (id !== 'tasks') return
  const sync = () => {
    taskStackRef.value?.syncPosition()
    if (animation.pending || animation.playState === 'running') {
      taskPanelSyncFrame = window.requestAnimationFrame(sync)
    } else {
      taskPanelSyncFrame = null
    }
  }
  if (taskPanelSyncFrame !== null) window.cancelAnimationFrame(taskPanelSyncFrame)
  taskPanelSyncFrame = window.requestAnimationFrame(sync)
}

function captureClick(event: MouseEvent) {
  if (!suppressNextClick.value) return
  event.preventDefault()
  event.stopPropagation()
}

function itemWidth(id: FloatingItemId) {
  return itemElements.get(id)?.offsetWidth || 120
}

function itemHeight(id: FloatingItemId) {
  return itemElements.get(id)?.offsetHeight || 42
}

function stopDragListeners() {
  window.removeEventListener('pointermove', handleDrag)
  window.removeEventListener('pointerup', finishDrag)
  window.removeEventListener('pointercancel', finishDrag)
}

function clamp(value: number, minimum: number, maximum: number) {
  return Math.max(minimum, Math.min(maximum, value))
}

function refreshPositions() {
  positions.value = { ...positions.value }
}

onMounted(() => window.addEventListener('resize', refreshPositions))
onBeforeUnmount(() => {
  stopDragListeners()
  if (taskPanelSyncFrame !== null) window.cancelAnimationFrame(taskPanelSyncFrame)
  window.removeEventListener('resize', refreshPositions)
})
</script>

<style scoped>
.floating-dock-layer { position: absolute; z-index: 20; inset: 0; overflow: hidden; pointer-events: none; }
.floating-dock-item { position: absolute; z-index: 2; pointer-events: auto; touch-action: none; user-select: none; will-change: transform, top, left; }
.floating-dock-item.side-left { left: 12px; right: auto; }
.floating-dock-item.side-right { right: 12px; left: auto; }
.floating-dock-item.is-dragging { z-index: 30; filter: drop-shadow(0 18px 28px color-mix(in srgb, var(--app-text) 20%, transparent)); cursor: grabbing; }
.floating-dock-item.is-dragging > * { transform: scale(1.035); }
.snap-guide { position: absolute; z-index: 1; top: 12%; bottom: 12%; width: 3px; border-radius: 999px; background: var(--app-text); opacity: .16; animation: guide-in .16s ease both; }
.guide-left { left: 5px; }
.guide-right { right: 5px; }
.dock-capsule, .dock-card {
  display: flex;
  align-items: center;
  gap: 7px;
  height: 38px;
  padding: 0 12px;
  border: 1px solid var(--app-border);
  border-radius: 999px;
  background: var(--app-surface);
  color: var(--app-text);
  font: inherit;
  font-size: 11px;
  font-weight: 620;
  cursor: grab;
  box-shadow: 0 7px 20px color-mix(in srgb, var(--app-text) 8%, transparent);
  transition: transform .2s cubic-bezier(.16, 1, .3, 1), border-color .18s ease, box-shadow .2s ease;
}
.dock-card { min-width: 104px; border-radius: 13px; }
.dock-capsule:hover, .dock-card:hover { transform: translateY(-2px); border-color: var(--app-text); box-shadow: 0 11px 26px color-mix(in srgb, var(--app-text) 12%, transparent); }
.side-right .dock-capsule, .side-right .dock-card { flex-direction: row-reverse; }
@keyframes guide-in { from { opacity: 0; transform: scaleY(.7); } to { opacity: .16; transform: scaleY(1); } }
@media (prefers-reduced-motion: reduce) { .dock-capsule, .dock-card, .snap-guide { animation: none; transition: none; } }
</style>

<style>
.dock-panel {
  overflow: hidden;
  border: 1px solid var(--app-border);
  border-radius: 18px;
  background: var(--app-surface);
  box-shadow: 0 24px 64px color-mix(in srgb, var(--app-text) 16%, transparent);
  animation: dock-panel-enter .24s cubic-bezier(.16, 1, .3, 1) both;
}
.workspace-panel-shell, .session-panel-shell { width: min(420px, calc(100vw - 44px)); max-height: min(68vh, 620px); overflow: auto; }
@keyframes dock-panel-enter { from { opacity: 0; transform: translateY(7px) scale(.97); } to { opacity: 1; transform: translateY(0) scale(1); } }
@media (prefers-reduced-motion: reduce) { .dock-panel { animation: none; } }
</style>
