<template>
  <article class="background-task-card" :class="`task-state-${view.status}`">
    <header class="task-header">
      <span class="task-mark" aria-hidden="true">
        <n-icon size="17"><component :is="kindIcon" /></n-icon>
      </span>
      <span class="task-heading">
        <strong>{{ view.title }}</strong>
        <small>{{ statusLabel }}</small>
      </span>
      <n-button
        v-if="!terminal"
        class="task-delete"
        size="tiny"
        quaternary
        :loading="cancelling"
        :disabled="view.status === 'cancelling'"
        @click="cancelTask"
      >
        {{ t('common.cancel') }}
      </n-button>
      <n-button
        v-if="terminal"
        class="task-delete"
        size="tiny"
        quaternary
        :loading="deleting"
        @click="deleteTask"
      >
        {{ t('backgroundTask.delete') }}
      </n-button>
    </header>

    <section class="task-current">
      <span class="status-dot" :class="`dot-${normalizeStatus(view.status)}`" />
      <span>
        <strong>{{ currentTitle }}</strong>
        <small>{{ currentDescription }}</small>
      </span>
    </section>

    <section v-if="view.reports.length" class="task-section">
      <h4>{{ t('backgroundTask.progressReports') }}</h4>
      <div class="progress-report-list">
        <div v-for="report in view.reports" :key="report.phaseId" class="progress-report-item">
          <span class="status-dot" :class="`dot-${normalizeStatus(report.status)}`" />
          <span>
            <strong>{{ report.title }}</strong>
            <small>{{ report.summary }}</small>
          </span>
          <time>{{ formatTime(report.occurredAt) }}</time>
        </div>
      </div>
    </section>

    <section v-if="interaction" class="task-interaction">
      <ToolApprovalPanel
        v-if="interaction.kind === 'tool_approval'"
        :requests="interaction.requests"
        @resolve="resolveApproval"
      />

      <PublishConfirmationPanel
        v-else-if="interaction.kind === 'publish_confirmation'"
        :publish-payload="interaction.payload"
        :revision-enabled="false"
        @published="refreshAfterPublish"
      />

      <template v-else-if="interaction.kind === 'resource_request' && interaction.workspace_id">
        <div class="interaction-copy">
          <strong>{{ interaction.title }}</strong>
          <p>{{ interaction.message }}</p>
        </div>
        <ResourceRequestPanel
          :workspace-id="interaction.workspace_id"
          :requests="resourceRequests"
          @configured="continueAfterResources"
          @skip="answerText = ''"
        />
      </template>

      <template v-else-if="interaction.kind === 'ask_user'">
        <div class="interaction-copy">
          <strong>{{ interaction.title }}</strong>
          <p>{{ interaction.message }}</p>
        </div>
        <div v-if="interaction.options.length" class="interaction-options">
          <button
            v-for="option in interaction.options"
            :key="String(option.value || option.label)"
            type="button"
            :class="{ selected: selectedOption === option.value }"
            @click="selectOption(String(option.value || option.label || ''))"
          >
            <strong>{{ option.label || option.value }}</strong>
            <small v-if="option.description">{{ option.description }}</small>
          </button>
        </div>
        <n-input
          v-if="allowFreeText"
          v-model:value="answerText"
          type="textarea"
          :autosize="{ minRows: 2, maxRows: 5 }"
          :placeholder="t('backgroundTask.responsePlaceholder')"
          @update:value="selectedOption = ''"
        />
        <div class="interaction-actions">
          <n-button
            size="small"
            type="primary"
            :loading="submitting"
            :disabled="!canSubmitAnswer"
            @click="submitAnswer"
          >
            {{ t('backgroundTask.submitResponse') }}
          </n-button>
        </div>
      </template>

      <div v-else class="interaction-copy">
        <strong>{{ interaction.title }}</strong>
        <p>{{ interaction.message }}</p>
      </div>
    </section>

    <section v-if="view.artifacts.length" class="task-section">
      <h4>{{ t('backgroundTask.artifacts') }}</h4>
      <div class="artifact-list">
        <span v-for="artifact in view.artifacts" :key="artifact.key">{{ artifact.name }}</span>
      </div>
    </section>

    <p v-if="actionError" class="task-notice task-notice-error">{{ actionError }}</p>
    <section v-if="view.error" class="task-notice task-notice-error">
      <strong>{{ t('common.error') }}</strong>
      <span>{{ view.error }}</span>
    </section>
  </article>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { NButton, NIcon, NInput } from 'naive-ui'
import { Bot, Upgrade } from '@vicons/carbon'
import { useI18n } from '@/composables/useI18n'
import {
  backgroundTasksApi,
  type BackgroundTask,
  type BackgroundTaskEvent,
  type InteractionAction,
} from '@/api/backgroundTasks'
import ToolApprovalPanel from './ToolApprovalPanel.vue'
import ResourceRequestPanel from './ResourceRequestPanel.vue'
import PublishConfirmationPanel from './PublishConfirmationPanel.vue'

const props = defineProps<{ task: BackgroundTask; fallbackTitle?: string }>()
const emit = defineEmits<{ updated: [task: BackgroundTask]; deleted: [taskId: string] }>()
const { t } = useI18n()
const submitting = ref(false)
const deleting = ref(false)
const cancelling = ref(false)
const answerText = ref('')
const selectedOption = ref('')
const actionError = ref('')
const task = ref<BackgroundTask>(props.task)
const events = ref<BackgroundTaskEvent[]>([])
let pollTimer: ReturnType<typeof setTimeout> | null = null

const interaction = computed(() => task.value.pending_interaction || null)
const kindIcon = computed(() => task.value.type === 'evolve' ? Upgrade : Bot)
const view = computed(() => buildView(task.value, events.value, props.fallbackTitle || t('backgroundTask.title')))
const terminal = computed(() => ['succeeded', 'failed', 'cancelled'].includes(view.value.status))
const statusLabel = computed(() => t(`backgroundTask.status.${view.value.status}` as any))
const currentTitle = computed(() => interaction.value?.title || statusLabel.value)
const currentDescription = computed(() => (
  interaction.value?.message
  || view.value.latestSummary
  || t(`backgroundTask.description.${task.value.status}` as any)
))
const allowFreeText = computed(() => interaction.value?.payload.allow_free_text !== false)
const canSubmitAnswer = computed(() => Boolean(answerText.value.trim() || selectedOption.value))
const resourceRequests = computed(() => interaction.value?.resource_requests.map(request => ({
  resource_id: String(request.resource_id || ''),
  description: request.description == null ? undefined : String(request.description),
  secret: Boolean(request.secret),
  required: Boolean(request.required),
  value_schema: isRecord(request.value_schema) ? request.value_schema : undefined,
  secret_fields: Array.isArray(request.secret_fields) ? request.secret_fields.map(String) : undefined,
})).filter(request => request.resource_id) || [])

onMounted(loadEvents)
onBeforeUnmount(stopPolling)
watch(() => props.task, value => { task.value = value }, { deep: true })
watch(() => props.task.task_id, () => {
  events.value = []
  answerText.value = ''
  selectedOption.value = ''
  void loadEvents()
})

async function loadEvents() {
  if (!task.value.task_id) return
  try {
    const eventResponse = await backgroundTasksApi.events(task.value.task_id, events.value.at(-1)?.seq || 0)
    const known = new Set(events.value.map(item => item.seq))
    for (const event of eventResponse.events) {
      if (!known.has(event.seq)) events.value.push(event)
    }
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : String(error)
  }
  if (!terminal.value) schedulePoll()
}

async function resolveApproval(payload: Record<string, unknown>) {
  const action = String(payload.action || '') as InteractionAction
  await resolveInteraction(action, payload)
}

async function submitAnswer() {
  const answer = answerText.value.trim() || selectedOption.value
  if (!answer) return
  await resolveInteraction('answer', {
    answer,
    selected_values: selectedOption.value ? [selectedOption.value] : [],
  })
}

function selectOption(value: string) {
  selectedOption.value = value
  answerText.value = ''
}

async function continueAfterResources(resourceIds: string[]) {
  await resolveInteraction('continue', { configured_resource_ids: resourceIds })
}

async function refreshAfterPublish() {
  actionError.value = ''
  try {
    task.value = (await backgroundTasksApi.get(task.value.task_id)).task
    emit('updated', task.value)
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : String(error)
  }
}

async function resolveInteraction(action: InteractionAction, payload: Record<string, unknown>) {
  const pending = interaction.value
  if (!pending || submitting.value) return
  submitting.value = true
  actionError.value = ''
  try {
    task.value = (await backgroundTasksApi.resolveInteraction(
      task.value.task_id,
      pending.interaction_id,
      action,
      payload,
    )).task
    answerText.value = ''
    selectedOption.value = ''
    emit('updated', task.value)
    schedulePoll()
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : String(error)
  } finally {
    submitting.value = false
  }
}

async function deleteTask() {
  if (!terminal.value || deleting.value) return
  deleting.value = true
  actionError.value = ''
  try {
    const response = await backgroundTasksApi.delete(task.value.task_id)
    if (response.deleted) emit('deleted', task.value.task_id)
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : String(error)
  } finally {
    deleting.value = false
  }
}

async function cancelTask() {
  if (terminal.value || cancelling.value || task.value.status === 'cancelling') return
  cancelling.value = true
  actionError.value = ''
  try {
    task.value = (await backgroundTasksApi.cancel(task.value.task_id, 'user_cancelled')).task
    emit('updated', task.value)
    schedulePoll()
  } catch (error) {
    actionError.value = error instanceof Error ? error.message : String(error)
  } finally {
    cancelling.value = false
  }
}

function schedulePoll() {
  stopPolling()
  pollTimer = setTimeout(() => void loadEvents(), 2000)
}

function stopPolling() {
  if (pollTimer) clearTimeout(pollTimer)
  pollTimer = null
}

function buildView(current: BackgroundTask, timeline: BackgroundTaskEvent[], fallbackTitle: string) {
  const reportsByPhase = new Map<string, { phaseId: string; title: string; summary: string; status: string; occurredAt: string }>()
  for (const event of timeline) {
    if (event.event_type !== 'background_task_progress_report') continue
    const phaseId = String(event.payload.phase_id || '').trim()
    const title = String(event.payload.title || '').trim()
    const summary = String(event.payload.summary || '').trim()
    if (!phaseId || !title || !summary) continue
    reportsByPhase.set(phaseId, {
      phaseId,
      title,
      summary,
      status: String(event.payload.status || 'completed'),
      occurredAt: String(event.payload.occurred_at || event.created_at),
    })
  }
  const reports = Array.from(reportsByPhase.values())
  return {
    title: current.task_text || fallbackTitle,
    status: current.status,
    reports,
    latestSummary: reports.at(-1)?.summary || '',
    artifacts: artifactViews(current),
    error: String(current.error?.message || ''),
  }
}

function artifactViews(current: BackgroundTask): Array<{ key: string; name: string }> {
  const artifacts = new Map<string, { key: string; name: string }>()
  for (const artifact of current.artifact_refs || []) {
    const key = String(artifact?.path || artifact?.id || '')
    if (key) artifacts.set(key, { key, name: String(artifact?.name || artifact?.path || key) })
  }
  return Array.from(artifacts.values())
}

function normalizeStatus(status: unknown): string {
  const value = String(status || '')
  return value === 'succeeded' ? 'succeeded' : value === 'failed' ? 'failed' : value === 'cancelled' ? 'cancelled' : 'running'
}

function formatTime(value: unknown): string {
  const parsed = new Date(String(value || ''))
  if (!Number.isFinite(parsed.getTime())) return ''
  return new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit' }).format(parsed)
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value))
}
</script>

<style scoped>
.background-task-card { display: grid; gap: 16px; padding: 18px; color: var(--app-text); background: var(--app-surface); }
.task-header { display: flex; align-items: center; gap: 11px; }
.task-mark { width: 34px; height: 34px; display: grid; place-items: center; border: 1px solid var(--app-border); border-radius: 11px; }
.task-heading { min-width: 0; flex: 1; display: grid; gap: 2px; }
.task-delete { flex: 0 0 auto; }
.task-heading strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 14px; }
.task-heading small, .task-section small, .task-current small { color: var(--app-text-muted); font-size: 12px; line-height: 1.5; }
.task-current { display: grid; grid-template-columns: auto 1fr; gap: 10px; align-items: start; padding: 12px; border: 1px solid var(--app-border); border-radius: 13px; }
.task-current > span:last-child { display: grid; gap: 3px; }
.status-dot { width: 8px; height: 8px; margin-top: 5px; border-radius: 50%; background: var(--app-text-muted); }
.dot-running { background: var(--app-text); box-shadow: 0 0 0 4px color-mix(in srgb, var(--app-text) 10%, transparent); }
.dot-succeeded { background: var(--app-success); }
.dot-failed, .dot-cancelled { background: var(--app-error); }
.task-section { display: grid; gap: 9px; }
.task-section h4 { margin: 0; font-size: 12px; }
.progress-report-list { display: grid; gap: 9px; }
.progress-report-item { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 9px; align-items: start; }
.progress-report-item > span:nth-child(2) { display: grid; gap: 2px; }
.progress-report-item time { color: var(--app-text-muted); font-size: 10px; }
.task-interaction { display: grid; gap: 12px; }
.task-interaction :deep(.tool-approval-panel), .task-interaction :deep(.resource-request-panel) { padding: 14px; box-shadow: none; }
.interaction-copy { display: grid; gap: 5px; }
.interaction-copy p { margin: 0; font-size: 13px; line-height: 1.6; white-space: pre-wrap; }
.interaction-options { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.interaction-options button { display: grid; gap: 3px; padding: 10px; text-align: left; color: var(--app-text); background: var(--app-surface); border: 1px solid var(--app-border); border-radius: 11px; cursor: pointer; }
.interaction-options button.selected { border-color: var(--app-text); box-shadow: inset 0 0 0 1px var(--app-text); }
.interaction-options small { color: var(--app-text-muted); }
.interaction-actions { display: flex; justify-content: flex-end; }
.artifact-list { display: flex; flex-wrap: wrap; gap: 6px; }
.artifact-list span { padding: 5px 8px; border: 1px solid var(--app-border); border-radius: 8px; font-size: 11px; }
.task-notice { display: grid; gap: 4px; margin: 0; padding: 10px; border-radius: 10px; font-size: 12px; }
.task-notice-error { color: var(--app-error); background: color-mix(in srgb, var(--app-error) 8%, transparent); }
</style>
