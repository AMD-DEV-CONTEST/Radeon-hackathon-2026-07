<template>
  <div ref="rootRef" class="message-part" :class="[`part-${part.type}`, { streaming: isStreaming }]">
    <details
      v-if="part.type === 'reasoning'"
      class="reasoning-panel"
      :open="isStreaming"
    >
      <summary class="reasoning-summary">
        <span class="summary-left">
          <span v-if="isStreaming" class="reasoning-live-dot" aria-hidden="true"></span>
          <span class="summary-title">{{ isStreaming ? t('roles.assistantReasoningActive') : t('roles.assistantReasoning') }}</span>
        </span>
        <span class="summary-chevron" aria-hidden="true">⌄</span>
      </summary>
      <div class="markdown-content reasoning-markdown" v-html="renderedReasoning"></div>
    </details>

    <div
      v-else-if="part.type === 'text' && part.format === 'markdown'"
      class="markdown-content"
      v-html="renderedText"
    ></div>

    <div v-else-if="part.type === 'text'" class="plain-content">
      {{ part.text }}
    </div>

    <button
      v-else-if="part.type === 'attachment' && attachmentImageUrl"
      type="button"
      class="message-image-card"
      :title="attachmentOpenable ? t('attachments.openInWorkspace') : part.attachment.name"
      :disabled="!attachmentOpenable"
      @click="openAttachment"
    >
      <img :src="attachmentImageUrl" :alt="part.attachment.name" />
      <span>{{ part.attachment.name }}</span>
    </button>

    <button
      v-else-if="part.type === 'attachment'"
      type="button"
      class="message-attachment-chip"
      :class="{ openable: attachmentOpenable }"
      :title="attachmentOpenable ? t('attachments.openInWorkspace') : part.attachment.name"
      :disabled="!attachmentOpenable"
      @click="openAttachment"
    >
      <ResourceIcon
        :name="part.attachment.name"
        :mime-type="part.attachment.mime_type"
        :kind="part.attachment.kind"
        :size="18"
        class="message-attachment-icon"
      />
      <span class="message-attachment-name">{{ part.attachment.name }}</span>
      <span class="message-attachment-kind">{{ attachmentKindLabel(part.attachment) }}</span>
    </button>

    <details
      v-else-if="part.type === 'tool_call' || part.type === 'tool_result'"
      class="inline-tool-part"
      :class="[`tool-state-${toolState}`]"
      :open="isToolActive || toolState === 'failed'"
    >
      <summary class="inline-tool-summary">
        <span class="tool-summary-main">
          <span class="tool-status-dot" aria-hidden="true"></span>
          <span class="tool-summary-copy">
            <span class="tool-kind">{{ toolKindLabel }}</span>
            <strong class="tool-name">{{ toolName }}</strong>
          </span>
        </span>
        <span class="tool-summary-side">
          <span class="tool-status-pill">{{ toolStatusLabel }}</span>
          <span class="summary-chevron" aria-hidden="true">⌄</span>
        </span>
      </summary>
      <div v-if="toolPayload" class="tool-detail">
        <div class="tool-detail-label">{{ toolDetailLabel }}</div>
        <pre>{{ toolPayload }}</pre>
      </div>
      <div v-else class="tool-empty">{{ t('tool.noPayload') }}</div>
    </details>

    <ToolExecutionCard
      v-else-if="part.type === 'tool_execution'"
      :part="part"
      :workspace-context="workspaceContext"
    />

    <a
      v-else-if="part.type === 'artifact' && artifactImageUrl"
      class="message-image-card"
      :href="artifactImageUrl"
      target="_blank"
      rel="noopener noreferrer"
    >
      <img :src="artifactImageUrl" :alt="part.name" />
      <span>{{ part.name }}</span>
    </a>

    <a
      v-else-if="part.type === 'artifact'"
      class="artifact-part"
      :href="artifactFileUrl || undefined"
      :target="artifactFileUrl ? '_blank' : undefined"
      :rel="artifactFileUrl ? 'noopener noreferrer' : undefined"
      @click="preventUnavailableArtifact"
    >
      <ResourceIcon :name="part.name" :mime-type="part.mimeType" :size="24" />
      <span class="artifact-copy">
        <strong>{{ part.name }}</strong>
        <small v-if="artifactMeta">{{ artifactMeta }}</small>
      </span>
    </a>

    <div v-else-if="part.type === 'error'" class="error-part">
      {{ part.message }}
    </div>

    <div v-else-if="part.type === 'status'" class="status-part">
      {{ part.message }}
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import ResourceIcon from '@/components/common/ResourceIcon.vue'
import ToolExecutionCard from '@/components/chat/ToolExecutionCard.vue'
import { useI18n } from '@/composables/useI18n'
import { useMarkdownRenderer } from '@/composables/useMarkdownRenderer'
import { useWorkspaceFileOpener } from '@/composables/useWorkspaceFileOpener'
import type { ChatMessagePart, TranscriptAttachmentView } from '@/types/protocol'
import type { WorkspaceRequestContext } from '@/api/resourceTypes'
import { isImageResource, workspaceResourceUrl } from '@/utils/workspaceResources'

const props = defineProps<{
  part: ChatMessagePart
  streaming?: boolean
  highlightMentions?: boolean
  mentionNames?: string[]
  workspaceContext?: WorkspaceRequestContext | null
}>()

const { t } = useI18n()
const { openWorkspaceFile } = useWorkspaceFileOpener()
const rootRef = ref<HTMLElement | null>(null)
const { renderMarkdown } = useMarkdownRenderer(rootRef)

const isStreaming = computed(() => props.streaming || props.part.status === 'streaming')
const renderedText = computed(() => (
  props.part.type === 'text'
    ? renderMarkdown(markdownWithMentions(props.part.text), {
        streaming: isStreaming.value,
        surface: 'chat_message',
        resolveImageUrl: resolveMessageImageUrl,
      })
    : ''
))
const renderedReasoning = computed(() => (
  props.part.type === 'reasoning'
    ? renderMarkdown(props.part.text, {
        streaming: isStreaming.value,
        surface: 'reasoning',
        resolveImageUrl: resolveMessageImageUrl,
      })
    : ''
))
const attachmentImageUrl = computed(() => {
  if (props.part.type !== 'attachment') return ''
  const attachment = props.part.attachment
  if (!attachment.path || !isImageResource(attachment.name, attachment.mime_type)) return ''
  return resolveMessageImageUrl(attachment.path) || ''
})
const attachmentOpenable = computed(() => (
  props.part.type === 'attachment'
  && Boolean(props.part.attachment.path && props.workspaceContext)
))
const artifactImageUrl = computed(() => {
  if (props.part.type !== 'artifact' || !props.part.path) return ''
  if (!isImageResource(props.part.path, props.part.mimeType)) return ''
  return resolveMessageImageUrl(props.part.path) || ''
})
const artifactFileUrl = computed(() => {
  if (props.part.type !== 'artifact' || !props.part.path) return ''
  return resolveMessageImageUrl(props.part.path) || ''
})
const artifactMeta = computed(() => {
  if (props.part.type !== 'artifact') return ''
  return [
    props.part.mimeType,
    typeof props.part.sizeBytes === 'number' ? formatFileSize(props.part.sizeBytes) : null,
  ].filter(Boolean).join(' · ')
})
const toolName = computed(() => (
  props.part.type === 'tool_call' || props.part.type === 'tool_result'
    ? props.part.toolName || 'tool'
    : ''
))
const toolKindLabel = computed(() => (
  props.part.type === 'tool_result' ? t('tool.result') : t('tool.call')
))
const toolState = computed(() => {
  const status = props.part.status || ''
  if (status === 'cancelled') return 'cancelled'
  if (status === 'failed') return 'failed'
  if (status === 'awaiting_approval') return 'approval'
  if (status === 'running' || status === 'streaming' || status === 'requested') return 'running'
  return 'completed'
})
const isToolActive = computed(() => toolState.value === 'running' || toolState.value === 'approval')
const toolStatusLabel = computed(() => {
  const status = props.part.status || ''
  if (status === 'cancelled') return t('tool.status.cancelled')
  if (status === 'awaiting_approval') return t('tool.status.waitingApproval')
  if (status === 'requested') return t('tool.status.proposed')
  if (status === 'running' || status === 'streaming') return t('tool.status.started')
  if (status === 'failed') return t('tool.status.failed')
  if (status === 'stopped') return t('run.stopped')
  return t('tool.status.completed')
})
const toolDetailLabel = computed(() => {
  if (props.part.type === 'tool_call') return t('tool.arguments')
  if (props.part.type === 'tool_result' && props.part.error) return t('common.error')
  return t('tool.result')
})
const toolPayload = computed(() => {
  if (props.part.type === 'tool_call') return valueString(props.part.arguments)
  if (props.part.type === 'tool_result') return valueString(props.part.error || props.part.output)
  return ''
})

function attachmentKindLabel(attachment: TranscriptAttachmentView): string {
  if (attachment.kind === 'url') return t('attachments.url')
  if (attachment.kind === 'text') return t('attachments.text')
  if (attachment.source_kind === 'workspace_file') return t('attachments.workspaceFile')
  return t('attachments.localFile')
}

async function openAttachment(): Promise<void> {
  if (props.part.type !== 'attachment' || !props.part.attachment.path) return
  await openWorkspaceFile(
    props.part.attachment.path,
    props.workspaceContext,
    props.part.attachment.workspace_scope || 'workdir',
  )
}

function resolveMessageImageUrl(source: string): string | null {
  return workspaceResourceUrl(source, props.workspaceContext)
}

function preventUnavailableArtifact(event: MouseEvent) {
  if (!artifactFileUrl.value) event.preventDefault()
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function valueString(value: unknown): string {
  if (value == null || value === '') return ''
  return typeof value === 'string' ? value : JSON.stringify(value, null, 2) || String(value)
}

function markdownWithMentions(content: string): string {
  if (!props.highlightMentions) return content
  const names = (props.mentionNames || [])
    .map(name => String(name).trim())
    .filter(Boolean)
    .sort((left, right) => right.length - left.length)
  if (!names.length) return content

  try {
    const alternatives = names.map(escapeRegExp).join('|')
    const mentionPattern = new RegExp(`@(${alternatives})(?=$|[\\s，。！？、,.!?;:])`, 'gu')
    return content.replace(mentionPattern, (_match, name: string) => `[@${name}](#agent-mention)`)
  } catch (error) {
    console.warn('Failed to create mention pattern:', error)
    return content
  }
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

</script>

<style scoped>
.message-part + .message-part {
  margin-top: var(--app-space-sm);
}

.message-part :deep(.markdown-content > :first-child) {
  margin-top: 0;
}

.message-part :deep(.markdown-content > :last-child) {
  margin-bottom: 0;
}

.reasoning-panel {
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  background: var(--app-surface-muted);
  overflow: hidden;
}

.reasoning-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-xs);
  padding: var(--app-space-sm) var(--app-space-md);
  cursor: pointer;
  color: var(--app-text-muted);
  font-size: 13px;
  user-select: none;
}

.summary-left,
.tool-summary-main,
.tool-summary-side {
  display: inline-flex;
  align-items: center;
  min-width: 0;
}

.summary-left {
  gap: var(--app-space-xs);
}

.summary-title {
  font-weight: 600;
}

.summary-chevron {
  flex: 0 0 auto;
  color: var(--app-text-subtle);
  transition: transform var(--app-transition-base);
}

details[open] > summary .summary-chevron {
  transform: rotate(180deg);
}

.reasoning-markdown {
  padding: 0 var(--app-space-md) var(--app-space-md);
  color: var(--app-text-muted);
}

.reasoning-live-dot {
  width: 7px;
  height: 7px;
  border-radius: var(--app-radius-pill);
  background: var(--app-info);
  animation: app-pulse-soft 1.4s ease-in-out infinite;
}

.plain-content {
  white-space: pre-wrap;
  word-break: break-word;
}

.message-part :deep(a[href="#agent-mention"]) {
  color: var(--app-info);
  font-weight: 600;
  text-decoration: none;
}

.message-attachment-chip {
  appearance: none;
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-xs);
  max-width: 100%;
  padding: 4px 8px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  background: var(--app-surface-muted);
  color: var(--app-text);
  font-size: 12px;
  text-align: left;
}

.message-attachment-chip.openable {
  cursor: pointer;
}

.message-attachment-chip.openable:hover {
  border-color: var(--app-primary);
  background: var(--app-surface-hover);
}

.message-image-card {
  appearance: none;
  padding: 0;
  border: 0;
  background: transparent;
  cursor: pointer;
  display: inline-grid;
  gap: var(--app-space-xs);
  max-width: min(600px, 100%);
  color: var(--app-text-muted);
  font-size: 12px;
  text-decoration: none;
  text-align: left;
}

.message-image-card img {
  display: block;
  max-width: 100%;
  max-height: 400px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
  box-shadow: var(--app-shadow-sm);
  object-fit: contain;
}

.message-image-card span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.message-attachment-icon {
  flex: 0 0 auto;
  color: var(--app-text-muted);
}

.message-attachment-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.message-attachment-kind {
  flex: 0 0 auto;
  color: var(--app-text-muted);
}

.inline-tool-part,
.artifact-part,
.error-part,
.status-part {
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  background: var(--app-surface-muted);
}

.artifact-part,
.error-part,
.status-part {
  padding: var(--app-space-sm) var(--app-space-md);
}

.artifact-part {
  display: inline-flex;
  max-width: 100%;
  align-items: center;
  gap: var(--app-space-sm);
  color: var(--app-text);
  text-decoration: none;
}

.artifact-copy {
  display: grid;
  min-width: 0;
}

.artifact-copy strong,
.artifact-copy small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.artifact-copy small {
  color: var(--app-text-muted);
}

.inline-tool-part {
  overflow: hidden;
  border-color: color-mix(in srgb, var(--app-info) 28%, var(--app-border));
  background: color-mix(in srgb, var(--app-info) 5%, var(--app-surface));
}

.inline-tool-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-sm);
  padding: 10px var(--app-space-md);
  font-size: 13px;
  color: var(--app-text);
  cursor: pointer;
  user-select: none;
}

.tool-summary-main {
  gap: 10px;
}

.tool-summary-side {
  gap: var(--app-space-sm);
  flex: 0 0 auto;
}

.tool-status-dot {
  width: 9px;
  height: 9px;
  flex: 0 0 auto;
  border-radius: var(--app-radius-pill);
  background: var(--app-info);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--app-info) 14%, transparent);
}

.tool-state-running .tool-status-dot,
.tool-state-approval .tool-status-dot {
  animation: app-pulse-soft 1.4s ease-in-out infinite;
}

.tool-state-completed .tool-status-dot {
  background: var(--app-success);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--app-success) 16%, transparent);
}

.tool-state-failed .tool-status-dot {
  background: var(--app-error);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--app-error) 16%, transparent);
}

.tool-summary-copy {
  display: grid;
  min-width: 0;
  gap: 1px;
}

.tool-kind {
  color: var(--app-text-muted);
  font-size: 11px;
  line-height: 1.2;
}

.tool-name {
  min-width: 0;
  overflow: hidden;
  color: var(--app-text);
  font-size: 14px;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tool-status-pill {
  padding: 2px 8px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-pill);
  background: var(--app-surface);
  color: var(--app-text-muted);
  font-size: 11px;
  line-height: 1.5;
  white-space: nowrap;
}

.tool-detail {
  border-top: 1px solid var(--app-border);
  background: var(--app-surface);
}

.tool-detail-label {
  padding: var(--app-space-sm) var(--app-space-md) 0;
  color: var(--app-text-muted);
  font-size: 12px;
  font-weight: 600;
}

.inline-tool-part pre {
  max-height: 420px;
  margin: 0;
  padding: var(--app-space-sm) var(--app-space-md) var(--app-space-md);
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
  border-radius: var(--app-radius-sm);
  background: transparent;
}

.tool-empty {
  padding: 0 var(--app-space-md) var(--app-space-md);
  color: var(--app-text-subtle);
  font-size: 12px;
}

.error-part {
  border-color: var(--app-error);
  color: var(--app-error);
}
</style>
