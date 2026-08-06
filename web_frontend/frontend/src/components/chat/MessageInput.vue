<template>
  <div class="message-input-container" @dragover.prevent @drop.prevent="handleFileDrop">
    <div v-if="disabled && disabledHint" class="input-disabled-guidance" aria-live="polite">
      <RouterLink
        v-if="disabledHintRoute"
        class="input-disabled-guidance-link"
        :to="disabledHintRoute"
      >
        <span>{{ disabledHint }}</span>
        <n-icon size="14"><ArrowForward /></n-icon>
      </RouterLink>
    </div>
    <div v-if="queuedMessages.length > 0" class="queued-message-tray">
      <div
        v-for="queuedMessage in queuedMessages"
        :key="queuedMessage.requestId"
        class="queued-message-card"
      >
        <div class="queued-message-copy">
          <span class="queued-message-status">
            {{ queuedMessage.steering
              ? t('chat.messageSteering')
              : t('chat.messageQueuedAt', { position: queuedMessage.position }) }}
          </span>
          <span class="queued-message-content">
            {{ queuedMessage.content || t('chat.attachmentMessage') }}
          </span>
        </div>
        <n-button
          size="small"
          text
          class="queued-message-action"
          :disabled="queuedMessage.steering"
          @click="emit('steer', queuedMessage.requestId)"
        >
          {{ queuedMessage.steering ? t('chat.steering') : t('chat.steer') }}
        </n-button>
      </div>
    </div>

    <div v-if="contextReferences.length > 0" class="attachments-preview context-references-preview">
      <div
        v-for="(reference, index) in contextReferences"
        :key="`${reference.source_kind}:${reference.name}:${index}`"
        class="attachment-item context-reference-item"
      >
        <ResourceIcon
          :name="reference.name"
          :mime-type="reference.mime_type"
          :kind="reference.source_kind === 'workspace_file' ? 'file' : 'text'"
          :size="18"
        />
        <span class="attachment-name">{{ reference.name }}</span>
        <n-text depth="3" class="reference-kind">{{ referenceKindLabel(reference.source_kind) }}</n-text>
        <n-button text size="small" @click="referenceStore.remove(index, normalizedReferenceScope)">
          <n-icon><Close /></n-icon>
        </n-button>
      </div>
    </div>

    <!-- 附件预览区 -->
    <div v-if="attachmentsEnabled && attachments.length > 0" class="attachments-preview">
      <div
        v-for="(attachment, index) in attachments"
        :key="index"
        class="attachment-item"
      >
        <ResourceIcon
          :name="attachment.name"
          :mime-type="attachment.mime_type"
          :kind="attachment.kind"
          :size="18"
        />
        <span class="attachment-name">{{ attachment.name }}</span>
        <n-button text size="small" @click="removeAttachment(index)">
          <n-icon><Close /></n-icon>
        </n-button>
      </div>
      <n-text depth="3" class="attachment-count">
        {{ t('attachments.limitHint', { count: attachments.length, max: maxAttachments }) }}
      </n-text>
    </div>

    <!-- 输入框 -->
    <div class="input-wrapper">
      <n-input
        ref="inputRef"
        v-model:value="inputText"
        type="textarea"
        :placeholder="placeholder"
        :disabled="disabled"
        :rows="rows"
        :autosize="{ minRows: rows, maxRows: maxRows }"
        @update:value="handleTextUpdate"
        @keydown="handleKeyDown"
        @paste="handlePaste"
      />
    </div>

    <!-- 操作栏 -->
    <div class="input-actions">
      <div class="left-actions">
        <n-button
          v-if="attachmentsEnabled"
          text
          @click="openAttachmentPicker"
          :disabled="disabled || remainingAttachmentSlots <= 0"
        >
          <template #icon>
            <n-icon><AttachOutline /></n-icon>
          </template>
          {{ t('attachments.add') }}
        </n-button>
        <input
          ref="attachmentFileInputRef"
          class="native-file-input"
          type="file"
          multiple
          :accept="fileCapabilities?.attachment_accept || ''"
          @change="handleAttachmentFileInput"
        />

        <n-select
          v-if="modelSelectorEnabled"
          class="model-selector"
          size="small"
          :value="selectedModelProfileId || ''"
          :options="modelOptions"
          :placeholder="modelOptions.length > 0
            ? t('chat.modelSelectorPlaceholder')
            : t('chat.modelPoolEmptyPlaceholder')"
          :disabled="disabled || modelOptions.length <= 1"
          filterable
          @update:value="handleModelSelect"
        />

        <n-popover v-if="reasoningControlEnabled" trigger="click" placement="top-start">
          <template #trigger>
            <n-button
              text
              class="reasoning-button"
              :disabled="disabled"
              :aria-label="t('chat.reasoningLabel')"
            >
              <template #icon>
                <n-icon><BulbOutline /></n-icon>
              </template>
              <span>{{ t('chat.reasoningLabel') }} · {{ reasoningLabel }}</span>
              <n-icon size="12" class="reasoning-caret"><CaretDown /></n-icon>
            </n-button>
          </template>
          <div class="reasoning-popover">
            <div class="reasoning-popover-header">
              <span>{{ t('chat.reasoningIntensity') }}</span>
            </div>
            <n-radio-group
              :value="reasoningSelectionValue"
              size="small"
              class="reasoning-options soft-segmented-control"
              :disabled="disabled"
              @update:value="handleReasoningSelect"
            >
              <n-radio-button
                v-for="option in reasoningOptions"
                :key="option.value"
                :value="option.value"
              >
                {{ option.label }}
              </n-radio-button>
            </n-radio-group>
          </div>
        </n-popover>

        <n-button
          v-if="!attachmentsEnabled"
          text
          disabled
          class="input-mode-label"
        >
          <template #icon>
            <n-icon><CodeSlash /></n-icon>
          </template>
          {{ t('attachments.textMode') }}
        </n-button>

        <slot name="auxiliary-action"></slot>
      </div>

      <div class="right-actions">
        <slot name="before-send"></slot>
        <span
          class="send-control"
          :class="{ 'has-queued': queuedCount > 0 }"
          :title="isRunning ? t('chat.queueSend') : t('common.send')"
        >
          <n-button
            type="primary"
            circle
            class="send-button"
            :disabled="!canSend"
            :aria-label="isRunning ? t('chat.queueSend') : t('common.send')"
            @click="handleSend"
          >
            <template #icon>
              <n-icon><Send /></n-icon>
            </template>
          </n-button>
          <span v-if="queuedCount > 0" class="queued-count" aria-hidden="true">
            {{ queuedCount > 9 ? '9+' : queuedCount }}
          </span>
        </span>

        <n-button
          v-if="isRunning"
          type="error"
          class="cancel-button"
          :aria-label="t('common.cancel')"
          @click="handleCancel"
        >
          {{ t('common.cancel') }}
          <template #icon>
            <n-icon><Stop /></n-icon>
          </template>
        </n-button>
      </div>
    </div>

    <!-- 附件选择器 -->
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted } from 'vue'
import { RouterLink, type RouteLocationRaw } from 'vue-router'
import { NInput, NButton, NIcon, NText, NPopover, NRadioButton, NRadioGroup, NSelect, useMessage } from 'naive-ui'
import { ArrowForward, AttachOutline, BulbOutline, CaretDown, Close, CodeSlash, Send, Stop } from '@/components/icons'
import ResourceIcon from '@/components/common/ResourceIcon.vue'
import { useI18n } from '@/composables/useI18n'
import { useFileCapabilities } from '@/composables/useFileCapabilities'
import { MAX_RUNTIME_ATTACHMENTS, extensionFromMimeType, pastedImageFiles, runtimeFileAttachmentFromFile } from '@/utils/attachments'
import type { ContextReferenceInput, QueuedMessageView, RuntimeAttachmentInput } from '@/types/protocol'
import { useContextReferenceStore } from '@/stores/contextReferences'

const { t } = useI18n()
const messageApi = useMessage()
const referenceStore = useContextReferenceStore()
const {
  capabilities: fileCapabilities,
  attachmentExtensions,
  error: fileCapabilitiesError,
  load: loadFileCapabilities,
} = useFileCapabilities()

const props = withDefaults(
  defineProps<{
    placeholder?: string
    disabled?: boolean
    isRunning?: boolean
    queuedCount?: number
    queuedMessages?: QueuedMessageView[]
    rows?: number
    maxRows?: number
    attachmentsEnabled?: boolean
    modelSelectorEnabled?: boolean
    modelOptions?: Array<{ label: string; value: string; disabled?: boolean }>
    selectedModelProfileId?: string | null
    reasoningControlEnabled?: boolean
    reasoningIntensity?: number | null
    referenceScope?: string
    disabledHint?: string
    disabledHintRoute?: RouteLocationRaw
  }>(),
  {
    placeholder: '',
    disabled: false,
    isRunning: false,
    queuedCount: 0,
    queuedMessages: () => [],
    rows: 3,
    maxRows: 10,
    attachmentsEnabled: true,
    modelSelectorEnabled: false,
    modelOptions: () => [],
    selectedModelProfileId: '',
    reasoningControlEnabled: false,
    reasoningIntensity: null,
    referenceScope: 'global',
    disabledHint: '',
  }
)

const emit = defineEmits<{
  send: [message: string, attachments: RuntimeAttachmentInput[]]
  cancel: []
  steer: [requestId: string]
  input: [value: string]
  'update:selectedModelProfileId': [value: string]
  'update:reasoningIntensity': [value: number | null]
}>()

const inputRef = ref()
const attachmentFileInputRef = ref<HTMLInputElement | null>(null)
const inputText = ref('')
const attachments = ref<RuntimeAttachmentInput[]>([])
const normalizedReferenceScope = computed(() => String(props.referenceScope || '').trim() || 'global')
const contextReferences = computed(() => referenceStore.references(normalizedReferenceScope.value))
const placeholder = computed(() => props.placeholder || t('chat.inputPlaceholder'))
const reasoningOptions = computed(() => [
  { label: t('chat.reasoningDefault'), value: -1 },
  { label: t('chat.reasoningOff'), value: 0 },
  { label: t('chat.reasoningLow'), value: 1 },
  { label: t('chat.reasoningMedium'), value: 2 },
  { label: t('chat.reasoningHigh'), value: 3 },
  { label: t('chat.reasoningMaximum'), value: 4 },
])
const reasoningSelectionValue = computed(() => props.reasoningIntensity ?? -1)
const reasoningLabel = computed(() => (
  reasoningOptions.value.find((option) => option.value === reasoningSelectionValue.value)?.label
  || reasoningOptions.value[0].label
))
const maxAttachments = MAX_RUNTIME_ATTACHMENTS
const remainingAttachmentSlots = computed(() => Math.max(0, maxAttachments - attachments.value.length - contextReferences.value.length))

const canSend = computed(() => {
  const hasText = inputText.value.trim().length > 0
  const hasAttachments = props.attachmentsEnabled && attachments.value.length > 0
  return (hasText || hasAttachments) && !props.disabled
})

function handleKeyDown(e: KeyboardEvent) {
  if (e.key !== 'Enter' || e.shiftKey || e.isComposing) return
  e.preventDefault()
  handleSend()
}

function handleTextUpdate(value: string) {
  inputText.value = value
  emit('input', value)
}

async function handlePaste(e: ClipboardEvent) {
  if (!props.attachmentsEnabled || props.disabled) return
  const files = pastedImageFiles(e, pastedImageName)
  if (files.length === 0) return
  e.preventDefault()
  const selectedFiles = files.slice(0, remainingAttachmentSlots.value)
  if (selectedFiles.length === 0) {
    showAttachmentLimitReached()
    return
  }
  const pastedAttachments = await Promise.all(selectedFiles.map((file) => runtimeFileAttachmentFromFile(file)))
  appendAttachments(pastedAttachments)
  if (selectedFiles.length < files.length) {
    showAttachmentLimitPartial(selectedFiles.length)
  }
}

function handleSend() {
  if (!canSend.value) return

  const message = inputText.value.trim()
  emit('send', message, props.attachmentsEnabled ? [...contextReferences.value, ...attachments.value] : [...contextReferences.value])

  // 清空输入
  inputText.value = ''
  attachments.value = []
  referenceStore.clear(normalizedReferenceScope.value)
}

function handleCancel() {
  emit('cancel')
}

function handleModelSelect(value: string) {
  emit('update:selectedModelProfileId', value || '')
}

function handleReasoningSelect(value: string | number) {
  const intensity = Number(value)
  emit('update:reasoningIntensity', intensity < 0 ? null : intensity)
}

function openAttachmentPicker() {
  if (!fileCapabilities.value) {
    messageApi.warning(fileCapabilitiesError.value || t('attachments.capabilitiesUnavailable'))
    void loadFileCapabilities()
    return
  }
  attachmentFileInputRef.value?.click()
}

async function handleAttachmentFileInput(event: Event) {
  const input = event.target as HTMLInputElement
  await appendFiles(Array.from(input.files || []))
  input.value = ''
}

async function handleFileDrop(event: DragEvent) {
  if (!props.attachmentsEnabled || props.disabled) return
  await appendFiles(Array.from(event.dataTransfer?.files || []))
}

async function appendFiles(files: File[]) {
  if (files.length === 0) return
  const accepted: File[] = []
  const rejected: string[] = []
  for (const file of files) {
    if (isAcceptedAttachmentFile(file)) accepted.push(file)
    else rejected.push(file.name)
  }
  if (rejected.length) {
    messageApi.warning(t('attachments.unsupportedFiles', { names: rejected.join(', ') }))
  }
  const selected = accepted.slice(0, remainingAttachmentSlots.value)
  if (selected.length < accepted.length) showAttachmentLimitPartial(selected.length)
  appendAttachments(await Promise.all(selected.map((file) => runtimeFileAttachmentFromFile(file))))
}

function isAcceptedAttachmentFile(file: File): boolean {
  const suffix = file.name.includes('.') ? `.${file.name.split('.').pop()?.toLowerCase()}` : ''
  return Boolean(suffix && attachmentExtensions.value.has(suffix))
}

function appendAttachments(nextAttachments: RuntimeAttachmentInput[]) {
  if (nextAttachments.length === 0) return
  const remaining = remainingAttachmentSlots.value
  if (remaining <= 0) {
    showAttachmentLimitReached()
    return
  }
  const accepted = nextAttachments.slice(0, remaining)
  attachments.value.push(...accepted)
  if (accepted.length < nextAttachments.length) {
    showAttachmentLimitPartial(accepted.length)
  }
}

function showAttachmentLimitReached() {
  messageApi.warning(t('attachments.limitReached', { max: maxAttachments }))
}

function showAttachmentLimitPartial(accepted: number) {
  messageApi.warning(t('attachments.limitPartial', { accepted, max: maxAttachments }))
}

function pastedImageName(file: File, index: number) {
  const indexSuffix = index > 0 ? `-${index + 1}` : ''
  return `${t('attachments.pastedImageName')}-${pasteTimestamp()}${indexSuffix}.${extensionFromMimeType(file.type)}`
}

function pasteTimestamp() {
  const now = new Date()
  const date = [now.getFullYear(), pad2(now.getMonth() + 1), pad2(now.getDate())].join('')
  const time = [pad2(now.getHours()), pad2(now.getMinutes()), pad2(now.getSeconds())].join('')
  return `${date}-${time}`
}

function pad2(value: number) {
  return String(value).padStart(2, '0')
}

function removeAttachment(index: number) {
  attachments.value.splice(index, 1)
}

function referenceKindLabel(sourceKind?: string): string {
  if (sourceKind === 'workspace_file') return t('references.workspaceFile')
  if (sourceKind === 'text_selection') return t('references.selection')
  return t('references.message')
}

// 聚焦输入框
function focus() {
  nextTick(() => {
    inputRef.value?.focus()
  })
}

function clearTrailingAtMention() {
  inputText.value = inputText.value.replace(/@[^\s@]*$/, '')
  emit('input', inputText.value)
  focus()
}

function restoreDraft(message: string, draftAttachments: RuntimeAttachmentInput[]) {
  inputText.value = message
  attachments.value = []
  referenceStore.clear(normalizedReferenceScope.value)
  draftAttachments.forEach(attachment => {
    if (isContextReference(attachment)) {
      referenceStore.add(attachment, normalizedReferenceScope.value)
    } else {
      attachments.value.push(attachment)
    }
  })
  emit('input', inputText.value)
  focus()
}

function isContextReference(attachment: RuntimeAttachmentInput): attachment is ContextReferenceInput {
  return attachment.source_kind === 'message_reference'
    || attachment.source_kind === 'workspace_file'
    || attachment.source_kind === 'text_selection'
}

watch(
  normalizedReferenceScope,
  scope => referenceStore.activate(scope),
  { immediate: true },
)

watch(
  () => props.attachmentsEnabled,
  (enabled) => {
    if (!enabled) {
      attachments.value = []
    }
  }
)

onMounted(() => {
  void loadFileCapabilities()
})

// 暴露方法
defineExpose({
  focus,
  clearTrailingAtMention,
  restoreDraft,
})
</script>

<style scoped>
.message-input-container {
  position: relative;
  display: flex;
  flex-direction: column;
  min-inline-size: 720px;
  gap: var(--app-space-md);
  padding: var(--app-space-md);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-xl);
  background: var(--app-surface);
  transition: border-color var(--app-transition-base), box-shadow var(--app-transition-base);
}

.message-input-container:focus-within {
  border-color: var(--app-border-focus);
  box-shadow: 0 0 0 3px var(--app-focus-shadow);
}

.input-disabled-guidance {
  position: absolute;
  top: -42px;
  right: var(--app-space-md);
  z-index: 3;
  opacity: 0;
  transform: translateY(5px);
  transition: opacity var(--app-transition-fast), transform var(--app-transition-fast);
}

.input-disabled-guidance::after {
  position: absolute;
  right: 0;
  bottom: -18px;
  left: 0;
  height: 18px;
  content: '';
}

.message-input-container:hover .input-disabled-guidance,
.input-disabled-guidance:focus-within {
  opacity: 1;
  transform: translateY(0);
}

.input-disabled-guidance-link {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 2px;
  border: 0;
  border-bottom: 1px solid var(--app-text);
  background: transparent;
  color: var(--app-text);
  font-size: var(--app-font-sm);
  font-weight: 600;
  cursor: pointer;
}

.input-disabled-guidance-link:hover {
  opacity: 0.68;
}

.queued-message-tray {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-xs);
  margin: calc(-1 * var(--app-space-xl)) var(--app-space-md) calc(-1 * var(--app-space-sm));
  z-index: 2;
}

.queued-message-card {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-md);
  padding: 10px 12px 10px 16px;
  border: 1px solid var(--app-text);
  border-radius: 22px;
  background: var(--app-surface);
  box-shadow: 0 10px 28px color-mix(in srgb, var(--app-text) 12%, transparent);
  transform-origin: 28px 100%;
  animation: queued-message-bubble-in 0.3s cubic-bezier(0.16, 1, 0.3, 1) both;
}

.queued-message-card:last-child::before {
  position: absolute;
  bottom: -7px;
  left: 26px;
  width: 13px;
  height: 13px;
  border-right: 1px solid var(--app-text);
  border-bottom: 1px solid var(--app-text);
  background: var(--app-surface);
  content: '';
  transform: rotate(45deg);
}

.queued-message-copy {
  display: flex;
  min-width: 0;
  align-items: baseline;
  gap: var(--app-space-sm);
}

.queued-message-status {
  flex: 0 0 auto;
  color: var(--app-text);
  font-size: var(--app-font-xs);
  font-weight: 650;
}

.queued-message-content {
  min-width: 0;
  overflow: hidden;
  color: var(--app-text);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.queued-message-action {
  flex: 0 0 auto;
  color: var(--app-text);
  font-weight: 650;
}

@keyframes queued-message-bubble-in {
  from {
    opacity: 0;
    transform: translateY(10px) scale(0.9);
  }

  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

@media (prefers-reduced-motion: reduce) {
  .queued-message-card {
    animation: none;
  }
}

.native-file-input {
  display: none;
}

.attachments-preview {
  display: flex;
  flex-wrap: wrap;
  gap: var(--app-space-sm);
  padding: var(--app-space-sm) var(--app-space-md);
  background: var(--app-surface-muted);
  border-radius: var(--app-radius-md);
  animation: app-fade-in 0.2s ease both;
}

.attachment-item {
  display: flex;
  align-items: center;
  min-width: 0;
  max-width: 100%;
  gap: var(--app-space-xs);
  padding: var(--app-space-xs) var(--app-space-sm);
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  font-size: var(--app-font-md);
  transition: border-color var(--app-transition-fast), transform var(--app-transition-fast);
  animation: app-pop-in 0.22s cubic-bezier(0.16, 1, 0.3, 1) both;
}

.attachment-item:hover {
  border-color: var(--app-border-hover);
}

.attachment-name {
  flex: 1 1 auto;
  min-width: 0;
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.attachment-count {
  align-self: center;
  margin-left: auto;
  font-size: var(--app-font-sm);
  white-space: nowrap;
}

.reference-kind {
  font-size: var(--app-font-sm);
  white-space: nowrap;
}

.input-wrapper {
  position: relative;
}

.input-wrapper :deep(.n-input) {
  --n-border: none !important;
  --n-border-hover: none !important;
  --n-border-focus: none !important;
  --n-box-shadow-focus: none !important;
  background: transparent;
}

.input-wrapper :deep(.n-input .n-input__textarea-el) {
  color: var(--app-text);
  padding: var(--app-space-xs) 0;
  font-size: var(--app-font-lg);
  line-height: var(--app-leading-normal);
}

.input-wrapper :deep(.n-input .n-input__placeholder) {
  color: var(--app-text-placeholder);
}

.input-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: nowrap;
  gap: var(--app-space-sm);
}

.left-actions,
.right-actions {
  display: flex;
  align-items: center;
  flex-wrap: nowrap;
  gap: var(--app-space-sm);
  min-width: 0;
}

.left-actions {
  flex: 1 1 auto;
}

.right-actions {
  flex: 0 0 auto;
  justify-content: flex-end;
  margin-left: auto;
}

.model-selector {
  flex: 0 1 180px;
  min-width: 140px;
  max-width: 100%;
  width: 180px;
}

.reasoning-button {
  gap: var(--app-space-xs);
  max-width: 100%;
  white-space: nowrap;
}

.reasoning-button span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.reasoning-caret {
  color: var(--app-text-muted);
}

.reasoning-popover {
  width: max-content;
  max-width: min(420px, calc(100vw - 32px));
  padding: var(--app-space-xs);
}

.reasoning-popover-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-sm);
  margin-bottom: var(--app-space-sm);
  color: var(--app-text-secondary);
  font-size: var(--app-font-sm);
}

.reasoning-options {
  display: flex;
  width: 100%;
}

.reasoning-options :deep(.n-radio-button) {
  flex: 1;
  text-align: center;
}

.send-control {
  position: relative;
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
}

.send-button,
.cancel-button {
  min-width: 0;
  transition: transform var(--app-transition-fast);
}

.send-button {
  border-radius: 50%;
}

.cancel-button {
  border-radius: var(--app-radius-md);
}

.queued-count {
  position: absolute;
  top: -5px;
  right: -5px;
  display: grid;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  place-items: center;
  border: 2px solid var(--app-surface);
  border-radius: 999px;
  background: var(--app-text);
  color: var(--app-surface);
  font-size: 9px;
  font-weight: 700;
  line-height: 1;
  opacity: 0.78;
}

.send-button:not(:disabled):active,
.cancel-button:not(:disabled):active {
  transform: scale(0.96);
}

.cancel-button {
  animation: app-pop-in 0.22s cubic-bezier(0.16, 1, 0.3, 1) both;
}
</style>
