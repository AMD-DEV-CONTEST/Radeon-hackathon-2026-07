<template>
  <details
    class="tool-execution-card"
    :class="[`tool-state-${state}`]"
    :open="active || state === 'failed'"
  >
    <summary class="tool-summary">
      <span class="tool-main">
        <span class="tool-icon-shell" :class="`tool-category-${presentation.category}`">
          <n-icon size="18"><component :is="categoryIcon" /></n-icon>
        </span>
        <span class="tool-copy">
          <strong>{{ displayName }}</strong>
          <span v-if="presentation.summary" class="tool-summary-text">{{ presentation.summary }}</span>
        </span>
      </span>
      <span class="tool-side">
        <span v-if="durationLabel" class="tool-duration">{{ durationLabel }}</span>
        <span class="tool-status">{{ statusLabel }}</span>
        <span class="summary-chevron" aria-hidden="true">⌄</span>
      </span>
    </summary>

    <div class="tool-body">
      <div v-if="resultFacts.length" class="tool-facts">
        <span v-for="fact in resultFacts" :key="fact">{{ fact }}</span>
      </div>

      <div v-if="transactionFiles.length" class="structured-results transaction-results">
        <div
          v-for="file in transactionFiles"
          :key="`${file.change_type}:${file.path}`"
          class="transaction-file"
        >
          <ResourceIcon :name="file.path" kind="file" :size="18" />
          <span class="transaction-file-path">{{ file.path }}</span>
          <span class="transaction-change" :class="`transaction-change-${file.change_type}`">
            {{ transactionChangeLabel(file.change_type) }}
          </span>
          <span class="transaction-lines">
            <b v-if="file.change_summary?.added_lines">+{{ file.change_summary.added_lines }}</b>
            <i v-if="file.change_summary?.removed_lines">-{{ file.change_summary.removed_lines }}</i>
          </span>
        </div>
      </div>

      <div v-else-if="grepMatches.length" class="structured-results grep-results">
        <div v-for="match in grepMatches" :key="`${match.path}:${match.line_number}`" class="grep-result">
          <strong>{{ match.path }}:{{ match.line_number }}</strong>
          <code>{{ match.line }}</code>
        </div>
      </div>

      <div v-else-if="workspaceEntries.length" class="structured-results entry-results">
        <a
          v-for="entry in workspaceEntries"
          :key="`${entry.type}:${entry.path}`"
          :href="workspacePathUrl(entry.path, entry.type) || undefined"
          :target="workspacePathUrl(entry.path, entry.type) ? '_blank' : undefined"
          :rel="workspacePathUrl(entry.path, entry.type) ? 'noopener noreferrer' : undefined"
          @click="preventUnavailablePath($event, entry.path, entry.type)"
        >
          <ResourceIcon
            :name="entry.name || entry.path"
            :kind="entry.type"
            :size="18"
          />
          <span>{{ entry.path }}</span>
        </a>
      </div>

      <div v-if="shellOutput" class="structured-results shell-output">
        <pre ref="shellOutputElement" @scroll="handleShellOutputScroll">{{ shellOutput }}</pre>
      </div>

      <details v-if="hasArguments" class="tool-section">
        <summary>{{ t('tool.arguments') }}</summary>
        <pre>{{ formattedArguments }}</pre>
      </details>

      <details v-if="hasOutput || part.error" class="tool-section" :open="state === 'failed'">
        <summary>{{ part.error ? t('common.error') : t('tool.result') }}</summary>
        <pre>{{ formattedOutput }}</pre>
      </details>

      <div v-if="part.artifacts.length" class="tool-artifacts">
        <a
          v-for="artifact in part.artifacts"
          :key="artifact.id"
          class="tool-artifact"
          :class="{ 'tool-artifact-image': isImageArtifact(artifact) }"
          :href="artifactUrl(artifact)"
          :target="artifactUrl(artifact) ? '_blank' : undefined"
          :rel="artifactUrl(artifact) ? 'noopener noreferrer' : undefined"
          @click="preventUnavailableArtifact($event, artifact)"
        >
          <img
            v-if="isImageArtifact(artifact) && artifactUrl(artifact)"
            class="tool-artifact-preview"
            :src="artifactUrl(artifact)"
            :alt="artifact.name"
          />
          <ResourceIcon
            v-else
            :name="artifact.name"
            :mime-type="artifact.mimeType"
            :size="22"
          />
          <span class="tool-artifact-details">
            <strong>{{ artifact.name }}</strong>
            <small>{{ artifactMeta(artifact) }}</small>
          </span>
        </a>
      </div>
    </div>
  </details>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { NIcon } from 'naive-ui'
import {
  Bot,
  Calendar,
  Document,
  Edit,
  Folder,
  Search,
  Terminal,
  ToolBox,
} from '@vicons/carbon'
import ResourceIcon from '@/components/common/ResourceIcon.vue'
import { useI18n } from '@/composables/useI18n'
import { isImageResource, workspaceResourceUrl } from '@/utils/workspaceResources'
import { toolPresentation } from '@/utils/toolPresentation'
import type {
  ArtifactMessagePart,
  ToolExecutionMessagePart,
} from '@/types/protocol'
import type { WorkspaceRequestContext } from '@/api/resourceTypes'

const props = withDefaults(defineProps<{
  part: ToolExecutionMessagePart
  workspaceContext?: WorkspaceRequestContext | null
}>(), {
  workspaceContext: null,
})

const { t } = useI18n()
const presentation = computed(() => toolPresentation(props.part.toolName, props.part.arguments))
const displayName = computed(() => (
  presentation.value.labelKey ? t(presentation.value.labelKey as any) : props.part.toolName
))
const state = computed(() => {
  if (props.part.status === 'cancelled') return 'cancelled'
  if (props.part.error || props.part.status === 'failed') return 'failed'
  if (props.part.status === 'awaiting_approval') return 'approval'
  if (['running', 'streaming', 'requested'].includes(String(props.part.status || ''))) return 'running'
  return 'completed'
})
const active = computed(() => state.value === 'running' || state.value === 'approval')
const statusLabel = computed(() => {
  if (state.value === 'cancelled') return t('tool.status.cancelled')
  if (state.value === 'failed') return t('tool.status.failed')
  if (state.value === 'approval') return t('tool.status.waitingApproval')
  if (state.value === 'running') return t('tool.status.started')
  if (resultRecord.value?.status === 'preview_ready') return t('tool.transaction.previewReady')
  if (resultRecord.value?.status === 'committed') return t('tool.transaction.committed')
  return t('tool.status.completed')
})
const categoryIcon = computed(() => ({
  read: Document,
  write: Edit,
  search: Search,
  process: Terminal,
  knowledge: Folder,
  scheduler: Calendar,
  agent: Bot,
  extension: ToolBox,
  generic: ToolBox,
}[presentation.value.category]))
const formattedArguments = computed(() => valueString(props.part.arguments))
const formattedOutput = computed(() => valueString(props.part.error || props.part.output))
const hasArguments = computed(() => hasValue(props.part.arguments))
const hasOutput = computed(() => hasValue(props.part.output))
const clockMs = ref(Date.now())
const timingActive = computed(() => (
  state.value === 'running'
  && Number.isFinite(Date.parse(String(props.part.startedAt || '')))
))
let clockTimer: ReturnType<typeof setInterval> | null = null

watch(timingActive, (active) => {
  if (clockTimer) {
    clearInterval(clockTimer)
    clockTimer = null
  }
  if (!active) return
  clockMs.value = Date.now()
  clockTimer = setInterval(() => {
    clockMs.value = Date.now()
  }, 200)
}, { immediate: true })

onBeforeUnmount(() => {
  if (clockTimer) clearInterval(clockTimer)
})

const durationMs = computed(() => {
  const direct = resultRecord.value?.duration_ms
  if (typeof direct === 'number' && Number.isFinite(direct)) return direct
  const startedAt = Date.parse(String(
    props.part.startedAt || (timingActive.value ? '' : props.part.createdAt) || '',
  ))
  const completedAt = timingActive.value
    ? clockMs.value
    : Date.parse(String(props.part.updatedAt || ''))
  return Number.isFinite(startedAt) && Number.isFinite(completedAt) && completedAt >= startedAt
    ? completedAt - startedAt
    : null
})
const durationLabel = computed(() => {
  const value = durationMs.value
  if (value == null) return ''
  return value < 1000 ? `${Math.round(value)} ms` : `${(value / 1000).toFixed(value < 10_000 ? 1 : 0)} s`
})
const resultRecord = computed<Record<string, any> | null>(() => {
  const value = props.part.output
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const record = value as Record<string, any>
  return record.output && typeof record.output === 'object' && !Array.isArray(record.output)
    ? record.output as Record<string, any>
    : record
})
const resultFacts = computed(() => {
  const result = resultRecord.value
  if (!result) return []
  const facts: string[] = []
  const matches = Array.isArray(result.matches) ? result.matches.length : null
  const entries = Array.isArray(result.entries) ? result.entries.length : null
  if (matches !== null) facts.push(t('tool.fact.matches', { count: matches }))
  if (entries !== null) facts.push(t('tool.fact.entries', { count: entries }))
  if (typeof result.replacements === 'number') facts.push(t('tool.fact.replacements', { count: result.replacements }))
  if (typeof result.bytes_written === 'number') facts.push(t('tool.fact.bytesWritten', { count: result.bytes_written }))
  if (typeof result.operations_count === 'number') {
    facts.push(t('tool.fact.operations', { count: result.operations_count }))
  }
  if (Array.isArray(result.affected_files)) {
    facts.push(t('tool.fact.affectedFiles', { count: result.affected_files.length }))
  }
  if (typeof result.exit_code === 'number') facts.push(t('tool.fact.exitCode', { code: result.exit_code }))
  if (result.truncated === true || result.stdout_truncated === true || result.stderr_truncated === true) {
    facts.push(t('tool.fact.truncated'))
  }
  return facts
})
const transactionFiles = computed<Array<Record<string, any>>>(() => {
  const files = resultRecord.value?.affected_files
  if (!Array.isArray(files)) return []
  return files.filter(file => (
    file
    && typeof file === 'object'
    && typeof file.path === 'string'
    && ['created', 'modified', 'deleted'].includes(String(file.change_type || ''))
  ))
})
const grepMatches = computed<Array<Record<string, any>>>(() => {
  const matches = resultRecord.value?.matches
  if (!Array.isArray(matches) || !matches.some(item => item && typeof item.line_number === 'number')) return []
  return matches.filter(item => item && typeof item === 'object').slice(0, 30)
})
const workspaceEntries = computed<Array<Record<string, any>>>(() => {
  const result = resultRecord.value
  const values = Array.isArray(result?.entries)
    ? result.entries
    : Array.isArray(result?.matches) && grepMatches.value.length === 0
      ? result.matches
      : []
  return values.filter(item => item && typeof item === 'object' && item.path).slice(0, 30)
})
const shellOutput = computed(() => {
  if (presentation.value.category !== 'process') return ''
  const stdout = String(resultRecord.value?.stdout || '').trim()
  const stderr = String(resultRecord.value?.stderr || '').trim()
  return [stdout, stderr].filter(Boolean).join('\n')
})
const shellOutputElement = ref<HTMLElement | null>(null)
const shellOutputPinned = ref(true)

watch(shellOutput, async () => {
  await nextTick()
  const element = shellOutputElement.value
  if (!element || !shellOutputPinned.value) return
  element.scrollTop = element.scrollHeight
})

function handleShellOutputScroll() {
  const element = shellOutputElement.value
  if (!element) return
  shellOutputPinned.value = element.scrollHeight - element.scrollTop - element.clientHeight < 24
}

function artifactUrl(artifact: ArtifactMessagePart): string {
  return artifact.path ? workspaceResourceUrl(artifact.path, props.workspaceContext) || '' : ''
}

function isImageArtifact(artifact: ArtifactMessagePart): boolean {
  return isImageResource(artifact.path || artifact.name, artifact.mimeType)
}

function workspacePathUrl(path: unknown, kind?: unknown): string {
  if (String(kind || '') === 'directory') return ''
  const value = String(path || '').trim()
  return value ? workspaceResourceUrl(value, props.workspaceContext) || '' : ''
}

function preventUnavailablePath(event: MouseEvent, path: unknown, kind?: unknown) {
  if (!workspacePathUrl(path, kind)) event.preventDefault()
}

function preventUnavailableArtifact(event: MouseEvent, artifact: ArtifactMessagePart) {
  if (!artifactUrl(artifact)) event.preventDefault()
}

function transactionChangeLabel(changeType: unknown): string {
  const key = {
    created: 'tool.transaction.created',
    modified: 'tool.transaction.modified',
    deleted: 'tool.transaction.deleted',
  }[String(changeType || '')] as
    | 'tool.transaction.created'
    | 'tool.transaction.modified'
    | 'tool.transaction.deleted'
    | undefined
  return key ? t(key) : String(changeType || '')
}

function artifactMeta(artifact: ArtifactMessagePart): string {
  const values = [
    artifact.mimeType,
    typeof artifact.sizeBytes === 'number' ? formatFileSize(artifact.sizeBytes) : null,
  ].filter(Boolean)
  return values.join(' · ')
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function hasValue(value: unknown): boolean {
  if (value == null || value === '') return false
  if (Array.isArray(value)) return value.length > 0
  if (typeof value === 'object') return Object.keys(value as Record<string, unknown>).length > 0
  return true
}

function valueString(value: unknown): string {
  if (value == null || value === '') return ''
  return typeof value === 'string' ? value : JSON.stringify(value, null, 2) || String(value)
}
</script>

<style scoped>
.tool-execution-card {
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--app-info) 24%, var(--app-border));
  border-radius: var(--app-radius-lg);
  background: color-mix(in srgb, var(--app-info) 4%, var(--app-surface));
}

.tool-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-md);
  padding: 10px var(--app-space-md);
  cursor: pointer;
  user-select: none;
}

.tool-main,
.tool-side {
  display: flex;
  align-items: center;
  min-width: 0;
}

.tool-main {
  gap: 10px;
}

.tool-side {
  flex: 0 0 auto;
  gap: var(--app-space-sm);
}

.tool-icon-shell {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  border-radius: var(--app-radius-md);
  background: color-mix(in srgb, var(--app-info) 12%, var(--app-surface));
  color: var(--app-info);
}

.tool-state-completed .tool-icon-shell {
  background: color-mix(in srgb, var(--app-success) 12%, var(--app-surface));
  color: var(--app-success);
}

.tool-state-failed .tool-icon-shell {
  background: color-mix(in srgb, var(--app-error) 12%, var(--app-surface));
  color: var(--app-error);
}

.tool-copy {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.tool-copy strong,
.tool-summary-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tool-copy strong {
  font-size: 13px;
}

.tool-summary-text,
.tool-duration {
  color: var(--app-text-muted);
  font-size: 11px;
}

.tool-status {
  padding: 2px 8px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-pill);
  background: var(--app-surface);
  color: var(--app-text-muted);
  font-size: 11px;
  white-space: nowrap;
}

.summary-chevron {
  color: var(--app-text-subtle);
  transition: transform var(--app-transition-base);
}

details[open] > summary .summary-chevron {
  transform: rotate(180deg);
}

.tool-body {
  border-top: 1px solid var(--app-border);
  background: var(--app-surface);
}

.tool-facts,
.tool-artifacts {
  display: flex;
  flex-wrap: wrap;
  gap: var(--app-space-sm);
  padding: var(--app-space-sm) var(--app-space-md);
}

.tool-facts span {
  padding: 3px 8px;
  border-radius: var(--app-radius-pill);
  background: var(--app-surface-muted);
  color: var(--app-text-muted);
  font-size: 11px;
}

.tool-section {
  border-top: 1px solid var(--app-divider);
}

.structured-results {
  border-top: 1px solid var(--app-divider);
  padding: var(--app-space-sm) var(--app-space-md);
}

.grep-results,
.entry-results,
.transaction-results {
  display: grid;
  gap: 6px;
  max-height: 320px;
  overflow: auto;
}

.transaction-file {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto auto;
  align-items: center;
  gap: var(--app-space-sm);
  min-width: 0;
  padding: 6px 8px;
  border-radius: var(--app-radius-sm);
  background: var(--app-surface-muted);
}

.transaction-file-path {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.transaction-change {
  padding: 2px 7px;
  border-radius: var(--app-radius-pill);
  color: var(--app-text-muted);
  font-size: 11px;
}

.transaction-change-created {
  background: color-mix(in srgb, var(--app-success) 14%, transparent);
  color: var(--app-success);
}

.transaction-change-modified {
  background: color-mix(in srgb, var(--app-info) 14%, transparent);
  color: var(--app-info);
}

.transaction-change-deleted {
  background: color-mix(in srgb, var(--app-error) 12%, transparent);
  color: var(--app-error);
}

.transaction-lines {
  display: flex;
  gap: 5px;
  min-width: 44px;
  justify-content: flex-end;
  font-size: 11px;
  font-style: normal;
}

.transaction-lines b {
  color: var(--app-success);
}

.transaction-lines i {
  color: var(--app-error);
  font-style: normal;
}

.grep-result {
  display: grid;
  gap: 2px;
  min-width: 0;
  padding: 6px 8px;
  border-radius: var(--app-radius-sm);
  background: var(--app-surface-muted);
}

.grep-result strong {
  overflow: hidden;
  color: var(--app-info);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.grep-result code {
  overflow: hidden;
  color: var(--app-text);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.entry-results a {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: var(--app-space-sm);
  padding: 5px 7px;
  border-radius: var(--app-radius-sm);
  color: var(--app-text);
  text-decoration: none;
}

.entry-results a:hover {
  background: var(--app-surface-muted);
}

.entry-results span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.shell-output pre {
  max-height: 320px;
  margin: 0;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--app-text);
  font-size: 12px;
}

.tool-section summary {
  padding: var(--app-space-sm) var(--app-space-md);
  color: var(--app-text-muted);
  cursor: pointer;
  font-size: 12px;
  font-weight: 600;
}

.tool-section pre {
  max-height: 420px;
  margin: 0;
  padding: 0 var(--app-space-md) var(--app-space-md);
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  background: transparent;
  font-size: 12px;
}

.tool-artifacts {
  border-top: 1px solid var(--app-divider);
}

.tool-artifact {
  display: flex;
  min-width: min(240px, 100%);
  align-items: center;
  gap: var(--app-space-sm);
  padding: 8px 10px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  color: var(--app-text);
  text-decoration: none;
}

.tool-artifact > span:last-child {
  display: grid;
  min-width: 0;
}

.tool-artifact-image {
  display: grid;
  width: min(420px, 100%);
  padding: 0;
  overflow: hidden;
}

.tool-artifact-preview {
  display: block;
  width: 100%;
  max-height: 320px;
  border-bottom: 1px solid var(--app-border);
  background: var(--app-surface-muted);
  object-fit: contain;
}

.tool-artifact-image .tool-artifact-details {
  padding: 9px 11px;
}

.tool-artifact strong,
.tool-artifact small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tool-artifact small {
  color: var(--app-text-muted);
}
</style>
