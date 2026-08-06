<template>
  <div class="extension-workbench">
    <header class="workbench-header">
      <div>
        <div class="eyebrow">{{ t('extensions.registryEyebrow') }}</div>
        <h1>{{ t('extensions.title') }}</h1>
        <p>{{ t('extensions.subtitle') }}</p>
      </div>
      <n-button quaternary circle class="refresh-button" @click="refreshExtensionWorkbench">
        <template #icon><n-icon><Refresh /></n-icon></template>
      </n-button>
    </header>

    <n-alert
      v-if="extensionStore.testResult && !showMcpModal"
      class="test-result"
      :type="testResultType"
      :title="testResultTitle"
      closable
      @close="extensionStore.setTestResult(null)"
    >
      <McpTestResultDetails :result="extensionStore.testResult" />
    </n-alert>

    <main class="workbench-grid">
      <section class="registry-panel">
        <div class="panel-glow" />
        <n-tabs v-model:value="activeRegistryTab" type="segment" animated class="registry-tabs">
          <n-tab-pane name="mcp" :tab="`MCP · ${extensionStore.mcpItems.length}`">
            <div class="registry-toolbar">
              <div>
                <strong>{{ t('extensions.globalMcpTitle') }}</strong>
                <span>{{ t('extensions.globalMcpHint') }}</span>
              </div>
              <n-button class="primary-action" @click="openAddMcp">
                <template #icon><n-icon><Add /></n-icon></template>
                {{ t('extensions.addServer') }}
              </n-button>
            </div>

            <div v-if="extensionStore.mcpItems.length" class="registry-cards">
              <article
                v-for="item in extensionStore.mcpItems"
                :key="extensionKey(item)"
                class="registry-card mcp-card"
                :class="{
                  'is-being-dragged': isDraggedExtension(
                    'mcp',
                    String(item.payload?.server_id || ''),
                  ),
                }"
                @pointerdown="beginPointerExtensionDrag(
                  $event,
                  'mcp',
                  String(item.payload?.server_id || ''),
                  extensionDisplayName(item),
                )"
              >
                <div class="card-topline">
                  <div class="card-icon">MCP</div>
                  <div class="drag-grip">{{ t('extensions.drag') }}</div>
                </div>
                <div class="card-body">
                  <div class="card-title-row">
                    <strong>{{ extensionDisplayName(item) }}</strong>
                  </div>
                  <p>{{ extensionDescription(item) }}</p>
                  <code>{{ mcpCommandLine(item) }}</code>
                </div>
                <div class="card-actions">
                  <n-button size="tiny" quaternary @click="handleTestMcp(item)">{{ t('extensions.test') }}</n-button>
                  <n-dropdown :options="mcpActions" @select="(key) => handleMcpAction(key, item)">
                    <n-button size="tiny" quaternary circle @click.stop>
                      <n-icon><EllipsisHorizontal /></n-icon>
                    </n-button>
                  </n-dropdown>
                </div>
              </article>
            </div>
            <n-empty v-else class="registry-empty" :description="t('extensions.noMcpServers')" />
          </n-tab-pane>

          <n-tab-pane name="skills" :tab="`Skill · ${extensionStore.skillItems.length}`">
            <section class="skillhub-strip">
              <div>
                <strong>{{ t('extensions.skillHubTitle') }}</strong>
                <span>{{ skillHubStatusMessage }}</span>
              </div>
              <n-input
                v-model:value="skillHubQuery"
                size="small"
                :placeholder="t('extensions.skillHubSearchPlaceholder')"
                :disabled="!skillHubCliAvailable"
                @keyup.enter="handleSkillHubSearch"
              />
              <n-button
                size="small"
                class="primary-action"
                :disabled="!skillHubCliAvailable || !skillHubQuery.trim()"
                @click="handleSkillHubSearch"
              >
                {{ t('extensions.searchSkillHub') }}
              </n-button>
            </section>

            <div v-if="skillHubItems.length" class="skillhub-results">
              <div v-for="item in skillHubItems" :key="item.install_name || item.name">
                <span>{{ item.name }}</span>
                <n-button size="tiny" @click="handleSkillHubInstall(item)">
                  {{ t('extensions.installSkill') }}
                </n-button>
              </div>
            </div>

            <div class="registry-toolbar">
              <div>
                <strong>{{ t('extensions.globalSkillTitle') }}</strong>
                <span>{{ t('extensions.globalSkillHint') }}</span>
              </div>
              <n-button class="primary-action" @click="openAddSkill">
                <template #icon><n-icon><Add /></n-icon></template>
                {{ t('extensions.addSkill') }}
              </n-button>
            </div>

            <div v-if="extensionStore.skillItems.length" class="registry-cards">
              <article
                v-for="item in extensionStore.skillItems"
                :key="extensionKey(item)"
                class="registry-card skill-card"
                :class="{
                  'is-being-dragged': isDraggedExtension(
                    'skill',
                    String(item.payload?.skill_id || ''),
                  ),
                }"
                @pointerdown="beginPointerExtensionDrag(
                  $event,
                  'skill',
                  String(item.payload?.skill_id || ''),
                  extensionDisplayName(item),
                )"
              >
                <div class="card-topline">
                  <div class="card-icon">SKILL</div>
                  <div class="drag-grip">{{ t('extensions.drag') }}</div>
                </div>
                <div class="card-body">
                  <div class="card-title-row"><strong>{{ extensionDisplayName(item) }}</strong></div>
                  <p>{{ extensionDescription(item) }}</p>
                  <code>{{ item.payload?.path || t('extensions.pathUnset') }}</code>
                </div>
                <n-dropdown :options="skillActions" @select="(key) => handleSkillAction(key, item)">
                  <n-button size="tiny" quaternary circle class="corner-action" @click.stop>
                    <n-icon><EllipsisHorizontal /></n-icon>
                  </n-button>
                </n-dropdown>
              </article>
            </div>
            <n-empty v-else class="registry-empty" :description="t('extensions.noSkills')" />
          </n-tab-pane>
        </n-tabs>
      </section>

      <section class="assembly-panel" :class="{ 'is-dragging': draggingExtension }">
        <div class="assembly-heading">
          <div>
            <div class="eyebrow">{{ t('extensions.assemblyEyebrow') }}</div>
            <h2>{{ t('extensions.selectAgent') }}</h2>
          </div>
          <span v-if="draggingExtension" class="drop-hint">{{ t('extensions.dragToAgent') }}</span>
        </div>

        <div class="picker-stage">
          <div class="picker-axis" aria-hidden="true">
            <span />
            <span />
          </div>
          <div
            ref="agentPicker"
            class="agent-picker"
            :class="{ 'is-pointer-dragging': pickerPointer.active }"
            @scroll="handlePickerScroll"
            @pointerdown="handlePickerPointerDown"
            @pointermove="handlePickerPointerMove"
            @pointerup="handlePickerPointerUp"
            @pointercancel="handlePickerPointerUp"
          >
            <div class="picker-spacer" aria-hidden="true" />
            <n-popover
              v-for="(target, index) in assemblyTargets"
              :key="target.id"
              trigger="hover"
              placement="left"
              :show-arrow="false"
              class="agent-extension-popover"
            >
              <template #trigger>
                <button
                  class="agent-wheel-item"
                  :data-agent-target-id="target.id"
                  :class="{
                    active: selectedAssemblyTargetId === target.id,
                    busy: assemblyBusyTargetId === target.id,
                    'is-drop-target': dragHoverTargetId === target.id,
                    'is-just-bound': recentlyBoundTargetId === target.id,
                  }"
                  :style="wheelItemStyle(index)"
                  @click="selectWheelTarget(index)"
                >
                  <span class="agent-index">{{ String(index + 1).padStart(2, '0') }}</span>
                  <span class="agent-name">{{ target.name }}</span>
                  <span v-if="dragHoverTargetId === target.id" class="drop-action">{{ t('extensions.releaseToAdd') }}</span>
                  <span v-else-if="recentlyBoundTargetId === target.id" class="drop-action">{{ t('extensions.added') }}</span>
                  <span v-else class="agent-count">{{ targetExtensionCount(target.id) }}</span>
                </button>
              </template>
              <div class="bound-popover">
                <div class="bound-title">
                  <strong>{{ target.name }}</strong>
                  <span>{{ t('extensions.boundExtensions') }}</span>
                </div>
                <div v-if="targetExtensions(target.id).length" class="bound-list">
                  <div v-for="item in targetExtensions(target.id)" :key="extensionKey(item)">
                    <span class="bound-kind">{{ item.kind === 'mcp' ? 'M' : 'S' }}</span>
                    <span>{{ item.name }}</span>
                    <n-button
                      size="tiny"
                      quaternary
                      @click="removeExtensionFromTarget(
                        target.id,
                        item.kind === 'mcp' ? 'mcp' : 'skill',
                        String(item.payload?.server_id || item.payload?.skill_id || ''),
                      )"
                    >
                      {{ t('extensions.removeBinding') }}
                    </n-button>
                  </div>
                </div>
                <n-empty v-else size="small" :description="t('extensions.noBoundExtensions')" />
              </div>
            </n-popover>
            <div class="picker-spacer" aria-hidden="true" />
          </div>

          <div class="selected-target-summary">
            <span>{{ t('extensions.currentTarget') }}</span>
            <strong>{{ selectedAssemblyTarget?.name || 'Agent' }}</strong>
            <small>{{ t('extensions.extensionCount', { count: targetExtensionCount(selectedAssemblyTarget?.id || '') }) }}</small>
            <div class="selected-extension-list">
              <span
                v-for="item in targetExtensions(selectedAssemblyTarget?.id || '')"
                :key="extensionKey(item)"
              >
                {{ item.name }}
              </span>
              <span v-if="!targetExtensions(selectedAssemblyTarget?.id || '').length" class="empty-selection">
                {{ t('extensions.noExtensions') }}
              </span>
            </div>
          </div>
        </div>

        <footer class="assembly-footer">
          {{ t('extensions.assemblySaveHint') }}
        </footer>
      </section>
    </main>

    <McpConfigModal
      v-model:show="showMcpModal"
      :item="editingMcp"
      :edit-config="editingMcpConfig"
      :edit-config-loading="editingMcpConfigLoading"
      :busy="busyKey === 'mcp:install'"
      :stopping="mcpInstallStopping"
      :install-result="mcpInstallDisplayResult"
      @submit="handleInstallMcp"
      @cancel-install="handleStopMcpInstall"
    />
    <SkillConfigModal
      v-model:show="showSkillModal"
      :item="editingSkill"
      @submit="handleSaveSkill"
    />

    <Teleport to="body">
      <div
        v-if="pointerDrag.started"
        class="extension-drag-preview"
        :style="pointerDragPreviewStyle"
      >
        <span>{{ pointerDrag.kind === 'mcp' ? 'MCP' : 'SKILL' }}</span>
        <strong>{{ pointerDrag.name }}</strong>
      </div>
      <div
        v-if="showcaseFlight.active"
        class="showcase-extension-flight"
        :class="{ 'is-moving': showcaseFlight.moving }"
        :style="showcaseFlightStyle"
      >
        <span>{{ showcaseFlight.kind === 'mcp' ? 'MCP' : 'SKILL' }}</span>
        <strong>{{ showcaseFlight.name }}</strong>
        <small>{{ t('extensions.bindingInProgress') }}</small>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import type { CSSProperties } from 'vue'
import {
  NAlert,
  NButton,
  NDropdown,
  NEmpty,
  NIcon,
  NInput,
  NPopover,
  NTabPane,
  NTabs,
} from 'naive-ui'
import { Add, EllipsisHorizontal, Refresh } from '@/components/icons'
import { useExtensionsManager } from '@/composables/extensions/useExtensionsManager'
import McpConfigModal from '@/components/extensions/McpConfigModal.vue'
import McpTestResultDetails from '@/components/extensions/McpTestResultDetails.vue'
import SkillConfigModal from '@/components/extensions/SkillConfigModal.vue'
import { useI18n } from '@/composables/useI18n'
import type { ExtensionItemView } from '@/types/protocol'

const { t } = useI18n()

function extensionDisplayName(item: ExtensionItemView): string {
  return String(item.name || item.payload?.display_name || item.payload?.server_id || item.payload?.skill_id || '').trim()
}

function extensionDescription(item: ExtensionItemView): string {
  return String(item.payload?.description || '').trim() || t('common.noDescription')
}
const {
  assemblyBusyTargetId,
  assemblyTargets,
  busyKey,
  draggingExtension,
  dropExtensionOnTarget,
  editingMcp,
  editingMcpConfig,
  editingMcpConfigLoading,
  editingSkill,
  extensionKey,
  extensionStore,
  finishExtensionDrag,
  handleInstallMcp,
  handleMcpAction,
  handleSaveSkill,
  handleSkillAction,
  handleSkillHubInstall,
  handleSkillHubSearch,
  handleStopMcpInstall,
  handleTestMcp,
  mcpActions,
  mcpCommandLine,
  mcpInstallDisplayResult,
  mcpInstallStopping,
  openAddMcp,
  openAddSkill,
  refreshExtensionWorkbench,
  removeExtensionFromTarget,
  selectedAssemblyTarget,
  selectedAssemblyTargetId,
  showMcpModal,
  showSkillModal,
  skillActions,
  skillHubCliAvailable,
  skillHubItems,
  skillHubQuery,
  skillHubStatusMessage,
  startExtensionDrag,
  targetExtensionCount,
  targetExtensions,
  testResultTitle,
  testResultType,
} = useExtensionsManager()

const WHEEL_ITEM_HEIGHT = 72
const SHOWCASE_BIND_EVENT = 'fastagentfactory:showcase-extension-bind'
const activeRegistryTab = ref<'mcp' | 'skills'>('mcp')
const agentPicker = ref<HTMLElement | null>(null)
const pickerPosition = ref(0)
const pickerScrollFrame = ref<number | null>(null)
const dragHoverTargetId = ref('')
const recentlyBoundTargetId = ref('')
const pointerDrag = reactive({
  active: false,
  started: false,
  pointerId: -1,
  startX: 0,
  startY: 0,
  x: 0,
  y: 0,
  kind: 'mcp' as 'mcp' | 'skill',
  identifier: '',
  name: '',
})
const pickerPointer = reactive({
  active: false,
  pointerId: -1,
  startY: 0,
  startScrollTop: 0,
  moved: false,
})
const showcaseFlight = reactive({
  active: false,
  moving: false,
  kind: 'mcp' as 'mcp' | 'skill',
  name: '',
  x: 0,
  y: 0,
  width: 0,
  height: 0,
})
const pointerDragPreviewStyle = computed<CSSProperties>(() => ({
  transform: `translate3d(${pointerDrag.x + 16}px, ${pointerDrag.y + 16}px, 0)`,
}))
const showcaseFlightStyle = computed<CSSProperties>(() => ({
  width: `${showcaseFlight.width}px`,
  height: `${showcaseFlight.height}px`,
  transform: `translate3d(${showcaseFlight.x}px, ${showcaseFlight.y}px, 0)`,
}))

function wheelItemStyle(index: number): CSSProperties {
  const delta = index - pickerPosition.value
  const distance = Math.abs(delta)
  const curveOffset = Math.min(distance * distance * 15, 90)
  return {
    '--wheel-x': `${curveOffset}px`,
    '--wheel-scale': String(Math.max(0.78, 1 - distance * 0.085)),
    '--wheel-opacity': String(Math.max(0.16, 1 - distance * 0.25)),
    '--wheel-tilt': `${Math.max(-28, Math.min(28, delta * -8))}deg`,
  } as CSSProperties
}

function updatePickerPosition(): void {
  if (!agentPicker.value) return
  pickerPosition.value = agentPicker.value.scrollTop / WHEEL_ITEM_HEIGHT
  const index = Math.max(
    0,
    Math.min(assemblyTargets.value.length - 1, Math.round(pickerPosition.value)),
  )
  const target = assemblyTargets.value[index]
  if (target) selectedAssemblyTargetId.value = target.id
}

function handlePickerScroll(): void {
  if (pickerScrollFrame.value !== null) cancelAnimationFrame(pickerScrollFrame.value)
  pickerScrollFrame.value = requestAnimationFrame(() => {
    pickerScrollFrame.value = null
    updatePickerPosition()
  })
}

function scrollToWheelIndex(index: number, behavior: ScrollBehavior = 'smooth'): void {
  agentPicker.value?.scrollTo({
    top: index * WHEEL_ITEM_HEIGHT,
    behavior,
  })
}

function selectWheelTarget(index: number): void {
  if (pickerPointer.moved) return
  scrollToWheelIndex(index)
}

function isDraggedExtension(kind: 'mcp' | 'skill', identifier: string): boolean {
  return draggingExtension.value?.kind === kind
    && draggingExtension.value.identifier === identifier
}

function beginPointerExtensionDrag(
  event: PointerEvent,
  kind: 'mcp' | 'skill',
  identifier: string,
  name: string,
): void {
  if (
    event.button !== 0
    || !identifier
    || (event.target instanceof Element && event.target.closest('button'))
  ) return
  pointerDrag.active = true
  pointerDrag.started = false
  pointerDrag.pointerId = event.pointerId
  pointerDrag.startX = event.clientX
  pointerDrag.startY = event.clientY
  pointerDrag.x = event.clientX
  pointerDrag.y = event.clientY
  pointerDrag.kind = kind
  pointerDrag.identifier = identifier
  pointerDrag.name = name
  window.addEventListener('pointermove', handleExtensionPointerMove)
  window.addEventListener('pointerup', handleExtensionPointerUp)
  window.addEventListener('pointercancel', handleExtensionPointerCancel)
}

async function handleWheelDrop(targetId: string): Promise<void> {
  dragHoverTargetId.value = ''
  await dropExtensionOnTarget(targetId)
  recentlyBoundTargetId.value = targetId
  window.setTimeout(() => {
    if (recentlyBoundTargetId.value === targetId) recentlyBoundTargetId.value = ''
  }, 900)
}

function handleExtensionPointerMove(event: PointerEvent): void {
  if (!pointerDrag.active || event.pointerId !== pointerDrag.pointerId) return
  pointerDrag.x = event.clientX
  pointerDrag.y = event.clientY
  if (!pointerDrag.started) {
    const distance = Math.hypot(
      event.clientX - pointerDrag.startX,
      event.clientY - pointerDrag.startY,
    )
    if (distance < 6) return
    pointerDrag.started = true
    startExtensionDrag(pointerDrag.kind, pointerDrag.identifier)
    document.body.classList.add('is-extension-pointer-dragging')
  }
  event.preventDefault()
  const element = document.elementFromPoint(event.clientX, event.clientY)
  const targetElement = element?.closest<HTMLElement>('[data-agent-target-id]')
  const targetId = targetElement?.dataset.agentTargetId || ''
  if (targetId === dragHoverTargetId.value) return
  dragHoverTargetId.value = targetId
  if (targetId) selectedAssemblyTargetId.value = targetId
}

function handleExtensionPointerUp(event: PointerEvent): void {
  if (!pointerDrag.active || event.pointerId !== pointerDrag.pointerId) return
  if (pointerDrag.started) event.preventDefault()
  const targetId = dragHoverTargetId.value
  const shouldBind = pointerDrag.started && Boolean(targetId)
  detachPointerDragListeners()
  if (shouldBind) {
    void finishPointerBinding(targetId)
    return
  }
  resetPointerDrag()
}

function handleExtensionPointerCancel(event: PointerEvent): void {
  if (!pointerDrag.active || event.pointerId !== pointerDrag.pointerId) return
  detachPointerDragListeners()
  resetPointerDrag()
}

async function finishPointerBinding(targetId: string): Promise<void> {
  try {
    await handleWheelDrop(targetId)
  } finally {
    resetPointerDrag()
  }
}

async function playShowcaseBinding(event: Event): Promise<void> {
  const detail = (event as CustomEvent<{
    kind?: 'mcp' | 'skill'
    identifier?: string
    targetId?: string
  }>).detail
  const kind = detail?.kind === 'skill' ? 'skill' : 'mcp'
  const identifier = String(detail?.identifier || '').trim()
  const targetId = String(detail?.targetId || '').trim()
  if (!identifier || !targetId || showcaseFlight.active) return

  activeRegistryTab.value = kind === 'skill' ? 'skills' : 'mcp'
  selectedAssemblyTargetId.value = targetId
  await nextTick()
  await new Promise<void>((resolve) => window.setTimeout(resolve, 520))

  const source = document.querySelector<HTMLElement>(
    `.registry-card.${kind === 'skill' ? 'skill-card' : 'mcp-card'}`,
  )
  const target = document.querySelector<HTMLElement>(
    `[data-agent-target-id="${CSS.escape(targetId)}"]`,
  )
  if (!source || !target) return

  const sourceRect = source.getBoundingClientRect()
  const targetRect = target.getBoundingClientRect()
  showcaseFlight.kind = kind
  showcaseFlight.name = source.querySelector<HTMLElement>('.card-title-row strong')?.textContent?.trim()
    || (kind === 'skill' ? 'Skill' : 'MCP')
  showcaseFlight.x = sourceRect.left
  showcaseFlight.y = sourceRect.top
  showcaseFlight.width = sourceRect.width
  showcaseFlight.height = sourceRect.height
  showcaseFlight.active = true
  showcaseFlight.moving = false
  startExtensionDrag(kind, identifier)
  dragHoverTargetId.value = targetId

  await nextTick()
  await new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())))
  showcaseFlight.moving = true
  showcaseFlight.x = targetRect.left + Math.max(0, targetRect.width - Math.min(sourceRect.width, 210)) / 2
  showcaseFlight.y = targetRect.top + Math.max(0, targetRect.height - Math.min(sourceRect.height, 72)) / 2
  showcaseFlight.width = Math.min(sourceRect.width, 210)
  showcaseFlight.height = Math.min(sourceRect.height, 72)

  await new Promise<void>((resolve) => window.setTimeout(resolve, 1700))
  await handleWheelDrop(targetId)
  showcaseFlight.active = false
  showcaseFlight.moving = false
  finishExtensionDrag()
  await new Promise<void>((resolve) => window.setTimeout(resolve, 950))
}

function detachPointerDragListeners(): void {
  window.removeEventListener('pointermove', handleExtensionPointerMove)
  window.removeEventListener('pointerup', handleExtensionPointerUp)
  window.removeEventListener('pointercancel', handleExtensionPointerCancel)
}

function resetPointerDrag(): void {
  document.body.classList.remove('is-extension-pointer-dragging')
  dragHoverTargetId.value = ''
  finishExtensionDrag()
  pointerDrag.active = false
  pointerDrag.started = false
  pointerDrag.pointerId = -1
  pointerDrag.identifier = ''
  pointerDrag.name = ''
}

function handlePickerPointerDown(event: PointerEvent): void {
  if (!agentPicker.value || event.button !== 0) return
  pickerPointer.active = true
  pickerPointer.pointerId = event.pointerId
  pickerPointer.startY = event.clientY
  pickerPointer.startScrollTop = agentPicker.value.scrollTop
  pickerPointer.moved = false
  agentPicker.value.setPointerCapture(event.pointerId)
}

function handlePickerPointerMove(event: PointerEvent): void {
  if (
    !pickerPointer.active
    || pickerPointer.pointerId !== event.pointerId
    || !agentPicker.value
  ) return
  const offset = event.clientY - pickerPointer.startY
  if (Math.abs(offset) > 4) pickerPointer.moved = true
  agentPicker.value.scrollTop = pickerPointer.startScrollTop - offset
}

function handlePickerPointerUp(event: PointerEvent): void {
  if (!pickerPointer.active || pickerPointer.pointerId !== event.pointerId) return
  pickerPointer.active = false
  pickerPointer.pointerId = -1
  if (agentPicker.value?.hasPointerCapture(event.pointerId)) {
    agentPicker.value.releasePointerCapture(event.pointerId)
  }
  scrollToWheelIndex(Math.round(pickerPosition.value))
  window.setTimeout(() => {
    pickerPointer.moved = false
  }, 0)
}

onMounted(() => {
  window.addEventListener(SHOWCASE_BIND_EVENT, playShowcaseBinding)
  void nextTick(() => {
    const selectedIndex = Math.max(
      0,
      assemblyTargets.value.findIndex((target) => target.id === selectedAssemblyTargetId.value),
    )
    pickerPosition.value = selectedIndex
    scrollToWheelIndex(selectedIndex, 'auto')
  })
})

onBeforeUnmount(() => {
  window.removeEventListener(SHOWCASE_BIND_EVENT, playShowcaseBinding)
  detachPointerDragListeners()
  document.body.classList.remove('is-extension-pointer-dragging')
})
</script>

<style scoped>
.extension-workbench {
  position: relative;
  height: 100%;
  overflow: auto;
  padding: 28px 30px 34px;
  color: var(--app-text);
  background: var(--app-surface);
}

.workbench-header {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 24px;
}

.eyebrow {
  color: var(--app-text-muted);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: .18em;
}

h1, h2 { margin: 5px 0 0; letter-spacing: -.035em; }
h1 { font-size: 28px; }
h2 { font-size: 20px; }
.workbench-header p { margin: 7px 0 0; color: var(--app-text-muted); }

.refresh-button {
  border: 1px solid var(--app-border);
  border-radius: 12px;
}

.primary-action {
  color: var(--app-surface);
  border-color: var(--app-text);
  border-radius: 10px;
  background: var(--app-text);
}
.primary-action:hover {
  color: var(--app-surface);
  border-color: var(--app-text);
  background: color-mix(in srgb, var(--app-text) 86%, transparent);
}
.test-result { margin-bottom: 18px; }

.workbench-grid {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: minmax(410px, .92fr) minmax(520px, 1.08fr);
  gap: 20px;
  min-height: 650px;
}

.registry-panel, .assembly-panel {
  position: relative;
  overflow: hidden;
  border: 1px solid var(--app-border);
  border-radius: 22px;
  background: var(--app-surface);
}

.registry-panel { padding: 18px; }
.panel-glow { display: none; }

.registry-tabs { position: relative; z-index: 1; }
.registry-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  padding: 17px 4px 14px;
}
.registry-toolbar > div { display: grid; gap: 3px; }
.registry-toolbar span, .skillhub-strip span { color: var(--app-text-muted); font-size: 12px; }

.registry-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(168px, 1fr));
  gap: 12px;
}
.registry-card {
  position: relative;
  display: flex;
  flex-direction: column;
  aspect-ratio: 1;
  min-width: 0;
  padding: 15px;
  border: 1px solid var(--app-border);
  border-radius: 16px;
  cursor: grab;
  user-select: none;
  background: var(--app-surface);
  transition: transform .2s ease, box-shadow .2s ease, border-color .2s ease, opacity .2s ease;
}
.registry-card:hover {
  transform: translateY(-3px);
  border-color: var(--app-text);
  box-shadow: 0 10px 28px color-mix(in srgb, var(--app-text) 9%, transparent);
}
.registry-card:active { cursor: grabbing; }
.registry-card.is-being-dragged {
  opacity: .36;
  transform: scale(.96);
  border-style: dashed;
}
.card-topline {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.drag-grip {
  color: var(--app-text-muted);
  font-size: 9px;
  font-weight: 700;
  letter-spacing: .14em;
}
.card-icon, .bound-kind {
  display: grid;
  place-items: center;
  border-radius: 8px;
  font-weight: 800;
}
.card-icon {
  width: auto;
  height: 26px;
  padding: 0 8px;
  color: var(--app-surface);
  font-size: 9px;
  letter-spacing: .08em;
  background: var(--app-text);
}
.card-body {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-width: 0;
  padding-top: 18px;
}
.card-title-row { display: flex; align-items: center; gap: 8px; }
.card-title-row strong {
  overflow: hidden;
  font-size: 15px;
  line-height: 1.25;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.card-body p {
  display: -webkit-box;
  overflow: hidden;
  margin: 9px 0 auto;
  color: var(--app-text-muted);
  font-size: 12px;
  line-height: 1.55;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
}
.card-body code {
  display: block;
  overflow: hidden;
  margin-top: 12px;
  padding-top: 9px;
  border-top: 1px solid var(--app-border);
  color: var(--app-text-muted);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.card-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 8px -5px -5px;
}
.corner-action {
  position: absolute;
  right: 10px;
  bottom: 10px;
}
.registry-empty { padding: 70px 0; }

.skillhub-strip {
  display: grid;
  grid-template-columns: minmax(145px, .8fr) minmax(160px, 1fr) auto;
  align-items: center;
  gap: 10px;
  margin: 14px 3px 4px;
  padding: 13px;
  border: 1px solid var(--app-border);
  border-radius: 14px;
  background: var(--app-surface-soft);
}
.skillhub-strip > div { display: grid; }
.skillhub-results { display: grid; gap: 6px; padding: 8px 3px; }
.skillhub-results > div {
  display: flex; justify-content: space-between; align-items: center;
  padding: 8px 10px; border-radius: 10px; background: var(--app-surface-soft);
}

.assembly-panel {
  min-height: 650px;
  padding: 24px;
  transition: border-color .2s ease, box-shadow .2s ease;
}
.assembly-panel.is-dragging {
  border-color: var(--app-text);
  box-shadow: inset 0 0 0 1px var(--app-text);
}
.assembly-heading { display: flex; justify-content: space-between; align-items: center; }
.drop-hint {
  padding: 7px 11px;
  border: 1px solid var(--app-text);
  border-radius: 10px;
  color: var(--app-surface);
  font-size: 12px;
  background: var(--app-text);
  animation: hintPulse 1.2s ease-in-out infinite;
}

.picker-stage {
  position: absolute;
  inset: 86px 24px 54px;
  display: grid;
  grid-template-columns: minmax(260px, 1.15fr) minmax(170px, .85fr);
  align-items: center;
  gap: 20px;
  overflow: hidden;
}
.agent-picker {
  position: relative;
  height: 430px;
  overflow-x: hidden;
  overflow-y: auto;
  padding: 0 28px 0 4px;
  cursor: grab;
  scrollbar-width: none;
  scroll-snap-type: y mandatory;
  overscroll-behavior: contain;
  perspective: 820px;
  mask-image: linear-gradient(
    to bottom,
    transparent 0,
    black 18%,
    black 82%,
    transparent 100%
  );
}
.agent-picker::-webkit-scrollbar { display: none; }
.agent-picker.is-pointer-dragging {
  cursor: grabbing;
  scroll-snap-type: none;
}
.picker-spacer {
  height: calc((430px - 72px) / 2);
  pointer-events: none;
}
.picker-axis {
  position: absolute;
  z-index: 2;
  top: 50%;
  left: 4px;
  width: calc(57.5% - 10px);
  height: 72px;
  pointer-events: none;
  transform: translateY(-50%);
}
.picker-axis::before {
  content: "";
  position: absolute;
  inset: 0;
  border: 1px solid var(--app-text);
  border-radius: 15px;
  opacity: .12;
}
.picker-axis span {
  position: absolute;
  top: 50%;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--app-text);
  transform: translateY(-50%);
}
.picker-axis span:first-child { left: -2px; }
.picker-axis span:last-child { right: -2px; }
.agent-wheel-item {
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
  width: calc(100% - 92px);
  height: 60px;
  margin: 6px 0;
  padding: 0 14px;
  border: 1px solid var(--app-border);
  border-radius: 14px;
  color: inherit;
  text-align: left;
  background: var(--app-surface);
  cursor: pointer;
  opacity: var(--wheel-opacity);
  scroll-snap-align: center;
  transform:
    translateX(var(--wheel-x))
    rotateX(var(--wheel-tilt))
    scale(var(--wheel-scale));
  transform-origin: left center;
  transition:
    color .18s ease,
    background .18s ease,
    border-color .18s ease,
    box-shadow .18s ease,
    opacity .08s linear,
    transform .08s linear;
}
.agent-wheel-item:hover {
  border-color: var(--app-text);
}
.agent-wheel-item.active {
  color: var(--app-surface);
  border-color: var(--app-text);
  background: var(--app-text);
  box-shadow: 0 12px 28px color-mix(in srgb, var(--app-text) 15%, transparent);
}
.agent-index {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 10px;
  opacity: .5;
}
.agent-name {
  overflow: hidden;
  font-size: 13px;
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.agent-count {
  display: grid; place-items: center;
  min-width: 24px;
  height: 24px;
  padding: 0 6px;
  border: 1px solid currentColor;
  border-radius: 8px;
  font-size: 11px;
  opacity: .65;
}
.agent-wheel-item.busy {
  opacity: .42 !important;
  pointer-events: none;
}
.agent-wheel-item.is-drop-target {
  z-index: 3;
  color: var(--app-surface);
  border-color: var(--app-text);
  background: var(--app-text);
  box-shadow:
    0 0 0 5px color-mix(in srgb, var(--app-text) 10%, transparent),
    0 16px 36px color-mix(in srgb, var(--app-text) 18%, transparent);
  animation: dropTargetBreath .72s ease-in-out infinite alternate;
}
.agent-wheel-item.is-just-bound {
  animation: boundConfirm .8s ease both;
}
.drop-action {
  padding: 5px 8px;
  border: 1px solid currentColor;
  border-radius: 8px;
  font-size: 10px;
  font-weight: 700;
  white-space: nowrap;
}
.is-dragging .agent-wheel-item:not(.is-drop-target) {
  border-style: dashed;
}
.selected-target-summary {
  display: flex;
  align-self: stretch;
  flex-direction: column;
  justify-content: center;
  min-width: 0;
  margin: 56px 0;
  padding: 24px;
  border: 1px solid var(--app-border);
  border-radius: 18px;
  background: var(--app-surface-soft);
}
.selected-target-summary > span,
.selected-target-summary small {
  color: var(--app-text-muted);
  font-size: 11px;
}
.selected-target-summary strong {
  overflow: hidden;
  margin: 7px 0 3px;
  font-size: 18px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.selected-extension-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 20px;
}
.selected-extension-list > span {
  max-width: 100%;
  overflow: hidden;
  padding: 5px 8px;
  border: 1px solid var(--app-border);
  border-radius: 8px;
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.selected-extension-list .empty-selection {
  border-style: dashed;
  color: var(--app-text-muted);
}

.assembly-footer {
  position: absolute;
  left: 24px; right: 24px; bottom: 20px;
  display: flex; align-items: center; justify-content: center; gap: 8px;
  color: var(--app-text-muted);
  font-size: 12px;
}

.bound-popover { width: 290px; padding: 4px; }
.bound-title { display: flex; justify-content: space-between; margin-bottom: 10px; }
.bound-title span { color: var(--app-text-muted); font-size: 11px; }
.bound-list { display: grid; gap: 6px; }
.bound-list > div {
  display: grid;
  grid-template-columns: 26px minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  padding: 7px;
  border-radius: 10px;
  background: var(--app-surface-soft);
}
.bound-kind {
  width: 26px;
  height: 26px;
  color: var(--app-surface);
  background: var(--app-text);
}

:global(.extension-drag-preview) {
  position: fixed;
  z-index: 100000;
  top: 0;
  left: 0;
  display: flex;
  align-items: center;
  gap: 9px;
  max-width: 240px;
  overflow: hidden;
  padding: 10px 14px;
  border: 1px solid var(--app-text);
  border-radius: 12px;
  color: var(--app-surface);
  font: 700 12px/1.2 system-ui, sans-serif;
  text-overflow: ellipsis;
  white-space: nowrap;
  background: var(--app-text);
  box-shadow: 0 12px 30px color-mix(in srgb, var(--app-text) 20%, transparent);
  pointer-events: none;
  will-change: transform;
}
:global(.extension-drag-preview span) {
  font-size: 9px;
  letter-spacing: .1em;
  opacity: .6;
}
:global(.extension-drag-preview strong) {
  overflow: hidden;
  text-overflow: ellipsis;
}
:global(.showcase-extension-flight) {
  position: fixed;
  z-index: 100001;
  top: 0;
  left: 0;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  overflow: hidden;
  padding: 12px 14px;
  border: 1px solid var(--app-text);
  border-radius: 16px;
  color: var(--app-text);
  background: var(--app-surface);
  box-shadow: 0 18px 42px color-mix(in srgb, var(--app-text) 22%, transparent);
  pointer-events: none;
  transform-origin: center;
  will-change: transform, width, height, border-radius, box-shadow;
}
:global(.showcase-extension-flight.is-moving) {
  border-radius: 20px;
  box-shadow: 0 28px 62px color-mix(in srgb, var(--app-text) 28%, transparent);
  transition:
    transform 1.65s cubic-bezier(.18, .84, .24, 1),
    width 1.65s cubic-bezier(.18, .84, .24, 1),
    height 1.65s cubic-bezier(.18, .84, .24, 1),
    border-radius 1.65s ease,
    box-shadow 1.65s ease;
}
:global(.showcase-extension-flight span) {
  padding: 5px 7px;
  border-radius: 7px;
  color: var(--app-surface);
  font-size: 9px;
  font-weight: 800;
  letter-spacing: .08em;
  background: var(--app-text);
}
:global(.showcase-extension-flight strong) {
  overflow: hidden;
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
:global(.showcase-extension-flight small) {
  color: var(--app-text-muted);
  font-size: 10px;
}
:global(body.is-extension-pointer-dragging) {
  cursor: grabbing !important;
  user-select: none !important;
}

@keyframes dropTargetBreath {
  from { transform: translateX(var(--wheel-x)) rotateX(var(--wheel-tilt)) scale(1.02); }
  to { transform: translateX(var(--wheel-x)) rotateX(var(--wheel-tilt)) scale(1.075); }
}
@keyframes boundConfirm {
  0% { transform: translateX(var(--wheel-x)) rotateX(var(--wheel-tilt)) scale(1); }
  45% { transform: translateX(var(--wheel-x)) rotateX(var(--wheel-tilt)) scale(1.08); }
  100% { transform: translateX(var(--wheel-x)) rotateX(var(--wheel-tilt)) scale(var(--wheel-scale)); }
}
@keyframes hintPulse { 50% { transform: scale(1.04); } }

@media (max-width: 1100px) {
  .workbench-grid { grid-template-columns: 1fr; }
  .assembly-panel { min-height: 620px; }
}

@media (prefers-reduced-motion: reduce) {
  .agent-wheel-item, .drop-hint { animation: none !important; }
}
</style>
