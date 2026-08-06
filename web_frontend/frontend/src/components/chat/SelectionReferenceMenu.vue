<template>
  <div
    v-if="visible"
    ref="menuRef"
    class="selection-reference-menu"
    :style="{ left: `${position.x}px`, top: `${position.y}px` }"
    role="menu"
  >
    <n-button text size="small" @click="addSelectionReference">
      <template #icon><n-icon><AddCircleOutline /></n-icon></template>
      {{ t('references.addSelection') }}
    </n-button>
    <n-button v-if="tipSourceKey" text size="small" @click="startTiping">
      <template #icon><TipingIcon :size="18" /></template>
      Tiping
    </n-button>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { NButton, NIcon, useMessage } from 'naive-ui'
import { AddCircleOutline } from '@/components/icons'
import { useI18n } from '@/composables/useI18n'
import { useContextReferenceStore } from '@/stores/contextReferences'
import { selectionContextReference } from '@/utils/contextReferences'
import { useTipStore } from '@/stores/tips'
import TipingIcon from './TipingIcon.vue'

const { t } = useI18n()
const message = useMessage()
const referenceStore = useContextReferenceStore()
const tipStore = useTipStore()
const visible = ref(false)
const menuRef = ref<HTMLElement | null>(null)
const selectedText = ref('')
const sourceLabel = ref('')
const tipSourceKey = ref('')
const selectionStart = ref<number | undefined>()
const selectionEnd = ref<number | undefined>()
const position = reactive({ x: 0, y: 0 })

function handleContextMenu(event: MouseEvent) {
  const selection = window.getSelection()
  const text = String(selection?.toString() || '').trim()
  if (!text || !selection?.rangeCount) {
    visible.value = false
    return
  }
  const target = event.target instanceof Element ? event.target : null
  const source = target?.closest('[data-reference-label]')
  const tipSource = target?.closest('[data-tip-source-key]')
  selectedText.value = text
  sourceLabel.value = String(source?.getAttribute('data-reference-label') || document.title || 'Application selection')
  const candidateTipKey = String(tipSource?.getAttribute('data-tip-source-key') || '')
  tipSourceKey.value = tipStore.hasSource(candidateTipKey) ? candidateTipKey : ''
  const selectionContainer = tipSource?.querySelector('.message-body') || tipSource
  const offsets = selectionContainer && selection
    ? selectionOffsets(selectionContainer, selection.getRangeAt(0))
    : null
  selectionStart.value = offsets?.start
  selectionEnd.value = offsets?.end
  position.x = event.clientX
  position.y = event.clientY
  visible.value = true
  event.preventDefault()
  nextTick(() => alignMenuToViewport(event.clientX, event.clientY))
}

function startTiping() {
  if (!tipSourceKey.value || !selectedText.value) return
  tipStore.beginSelection(
    tipSourceKey.value,
    selectedText.value,
    selectionStart.value,
    selectionEnd.value,
  )
  visible.value = false
}

function addSelectionReference() {
  if (!selectedText.value) return
  if (!referenceStore.add(selectionContextReference(selectedText.value, sourceLabel.value))) {
    message.warning(t('references.limitReached'))
  } else {
    message.success(t('references.added'))
  }
  visible.value = false
}

function closeMenu() {
  visible.value = false
}

function selectionOffsets(container: Element, range: Range): { start: number; end: number } | null {
  if (!container.contains(range.commonAncestorContainer)) return null
  const prefix = range.cloneRange()
  prefix.selectNodeContents(container)
  prefix.setEnd(range.startContainer, range.startOffset)
  const start = prefix.toString().length
  return { start, end: start + range.toString().length }
}

function alignMenuToViewport(anchorX: number, anchorY: number) {
  const menu = menuRef.value
  if (!menu) return
  const margin = 8
  const bounds = menu.getBoundingClientRect()
  position.x = Math.max(margin, Math.min(anchorX, window.innerWidth - bounds.width - margin))
  position.y = Math.max(margin, Math.min(anchorY, window.innerHeight - bounds.height - margin))
}

onMounted(() => {
  document.addEventListener('contextmenu', handleContextMenu)
  document.addEventListener('click', closeMenu)
  window.addEventListener('blur', closeMenu)
  window.addEventListener('scroll', closeMenu, true)
})

onBeforeUnmount(() => {
  document.removeEventListener('contextmenu', handleContextMenu)
  document.removeEventListener('click', closeMenu)
  window.removeEventListener('blur', closeMenu)
  window.removeEventListener('scroll', closeMenu, true)
})
</script>

<style scoped>
.selection-reference-menu {
  position: fixed;
  z-index: 10000;
  width: 220px;
  padding: var(--app-space-xs) var(--app-space-sm);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  background: var(--app-surface-elevated);
  box-shadow: var(--app-shadow-lg);
  display: grid;
  gap: var(--app-space-xs);
}

.selection-reference-menu :deep(.n-button) {
  width: 100%;
  justify-content: flex-start;
  padding: 0 var(--app-space-sm);
}

.selection-reference-menu :deep(.n-button__content) {
  width: 100%;
  justify-content: flex-start;
  text-align: left;
}

.selection-reference-menu :deep(.n-button__icon) {
  width: 18px;
  min-width: 18px;
  margin-right: var(--app-space-xs);
}
</style>
