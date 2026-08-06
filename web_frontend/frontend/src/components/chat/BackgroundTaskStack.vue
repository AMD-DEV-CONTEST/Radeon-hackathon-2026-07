<template>
  <n-popover
    ref="popoverRef"
    v-if="visibleTasks.length && primaryTask"
    trigger="click"
    :show="expanded"
    :placement="side === 'left' ? 'bottom-start' : 'bottom-end'"
    :flip="false"
    :show-arrow="false"
    raw
    @update:show="expanded = $event"
  >
    <template #trigger>
      <button
        class="task-stack-summary"
        :class="{ 'has-multiple': visibleTasks.length > 1, 'requires-action': requiresAction }"
        type="button"
        :aria-expanded="expanded"
      >
        <span class="task-stack-mark" :class="{ 'is-active': hasActiveTasks }" aria-hidden="true">
          <span v-if="hasActiveTasks" class="task-stack-spinner" />
          <span v-else>✓</span>
        </span>
        <span class="task-stack-copy">
          <strong>{{ capsuleTitle }}</strong>
          <small v-if="visibleTasks.length > 1">{{ t('backgroundTask.stackCount', { count: visibleTasks.length }) }}</small>
        </span>
        <span class="task-stack-chevron" aria-hidden="true">⌄</span>
      </button>
    </template>

    <section class="task-stack-popover" :class="`dock-side-${side}`">
      <header class="stack-popover-header">
        <div>
          <strong>{{ t('backgroundTask.stackTitle') }}</strong>
          <small>{{ t('backgroundTask.stackCount', { count: visibleTasks.length }) }}</small>
        </div>
        <button type="button" :aria-label="t('common.close')" @click="expanded = false">×</button>
      </header>
      <div class="task-stack-list">
        <BackgroundTaskCard
          v-for="task in visibleTasks"
          :key="task.task_id"
          :task="task"
          @updated="reconcileOne"
          @deleted="removeTask"
        />
      </div>
    </section>
  </n-popover>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { NPopover } from 'naive-ui'
import { backgroundTasksApi, type BackgroundTask } from '@/api/backgroundTasks'
import { useI18n } from '@/composables/useI18n'
import BackgroundTaskCard from './BackgroundTaskCard.vue'

const props = withDefaults(defineProps<{
  sessionId?: string | null
  compact?: boolean
  side?: 'left' | 'right'
}>(), {
  sessionId: null,
  compact: false,
  side: 'left',
})

const { t } = useI18n()
const popoverRef = ref<{ syncPosition: () => void } | null>(null)
const tasks = ref<BackgroundTask[]>([])
const expanded = ref(false)
let pollTimer: ReturnType<typeof setTimeout> | null = null
let requestVersion = 0
const TERMINAL_TASK_VISIBILITY_MS = 60_000

defineExpose({ syncPosition })

const visibleTasks = computed(() => {
  const active = tasks.value.filter(task => !isTerminal(task.status)).sort(compareNewest)
  const completed = tasks.value
    .filter(task => isTerminal(task.status) && terminalStillVisible(task))
    .sort(compareNewest)
  return [...active, ...completed]
})
const primaryTask = computed(() => visibleTasks.value[0] || null)
const hasActiveTasks = computed(() => visibleTasks.value.some(task => !isTerminal(task.status)))
const requiresAction = computed(() => visibleTasks.value.some(task => (
  task.pending_interaction?.kind === 'tool_approval'
  || task.pending_interaction?.kind === 'publish_confirmation'
  || task.pending_interaction?.kind === 'ask_user'
  || task.pending_interaction?.kind === 'resource_request'
)))
const capsuleTitle = computed(() => {
  const task = primaryTask.value
  if (!task) return t('backgroundTask.stackTitle')
  const prefix = task.pending_interaction?.kind === 'tool_approval'
    ? t('backgroundTask.capsule.approval')
    : task.pending_interaction?.kind === 'publish_confirmation'
      ? t('publish.confirm')
    : task.pending_interaction?.kind === 'ask_user' || task.pending_interaction?.kind === 'resource_request'
      ? t('backgroundTask.capsule.answer')
      : taskTypeLabel(task.type, task.status)
  const target = task.assignee_package_id || task.task_text || t('backgroundTask.stackTitle')
  return `${prefix} · ${target}`
})

watch(requiresAction, (next, previous) => {
  if (next && !previous) expanded.value = true
})

watch(
  () => props.sessionId,
  () => {
    requestVersion += 1
    stopPolling()
    tasks.value = []
    expanded.value = false
    void refreshTasks(requestVersion)
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  requestVersion += 1
  stopPolling()
})

async function refreshTasks(version: number) {
  const sessionId = String(props.sessionId || '').trim()
  if (!sessionId) return
  try {
    const response = await backgroundTasksApi.list({ sessionId })
    if (version !== requestVersion || sessionId !== String(props.sessionId || '').trim()) return
    tasks.value.splice(0, tasks.value.length, ...response.tasks)
  } catch (error) {
    console.warn('Failed to refresh background tasks:', error)
  } finally {
    if (version === requestVersion) pollTimer = setTimeout(() => void refreshTasks(version), 2000)
  }
}

function reconcileOne(updated: BackgroundTask) {
  const index = tasks.value.findIndex(task => task.task_id === updated.task_id)
  if (index >= 0) tasks.value.splice(index, 1, updated)
}

function removeTask(taskId: string) {
  const index = tasks.value.findIndex(task => task.task_id === taskId)
  if (index >= 0) tasks.value.splice(index, 1)
}

function stopPolling() {
  if (pollTimer) clearTimeout(pollTimer)
  pollTimer = null
}

function syncPosition() {
  popoverRef.value?.syncPosition()
}

function isTerminal(status: BackgroundTask['status']): boolean {
  return status === 'succeeded' || status === 'failed' || status === 'cancelled'
}

function terminalStillVisible(task: BackgroundTask): boolean {
  if (task.pending_interaction?.kind === 'publish_confirmation') return true
  const timestamp = Date.parse(task.completed_at || task.updated_at || task.created_at)
  return Number.isFinite(timestamp) && Date.now() - timestamp < TERMINAL_TASK_VISIBILITY_MS
}

function compareNewest(left: BackgroundTask, right: BackgroundTask): number {
  return Date.parse(right.updated_at || right.created_at) - Date.parse(left.updated_at || left.created_at)
}

function taskTypeLabel(type: BackgroundTask['type'], status: BackgroundTask['status']): string {
  if (status === 'queued') return t('backgroundTask.capsule.queued')
  if (status === 'succeeded') return t('backgroundTask.capsule.completed')
  if (status === 'failed') return t('backgroundTask.capsule.failed')
  if (status === 'cancelled' || status === 'cancelling') return t('backgroundTask.capsule.stopping')
  if (type === 'manufacture') return t('backgroundTask.capsule.manufacturing')
  if (type === 'evolve') return t('backgroundTask.capsule.evolving')
  return t('backgroundTask.capsule.delegating')
}
</script>

<style scoped>
.task-stack-summary { min-height: 42px; max-width: min(320px, calc(100vw - 48px)); display: flex; align-items: center; gap: 9px; padding: 6px 12px 6px 7px; color: var(--app-text); background: var(--app-surface); border: 1px solid var(--app-border); border-radius: 999px; box-shadow: 0 10px 28px color-mix(in srgb, var(--app-text) 11%, transparent); cursor: pointer; transition: transform .2s cubic-bezier(.16, 1, .3, 1), border-color .2s ease, box-shadow .2s ease; }
.task-stack-summary:hover { transform: translateY(-1px); border-color: var(--app-border-hover); box-shadow: 0 14px 34px color-mix(in srgb, var(--app-text) 14%, transparent); }
.task-stack-summary.requires-action { border-color: var(--app-text); }
.task-stack-mark { width: 29px; height: 29px; flex: 0 0 auto; display: grid; place-items: center; border: 1px solid var(--app-border); border-radius: 50%; font-size: 11px; }
.task-stack-spinner { width: 13px; height: 13px; border: 2px solid var(--app-divider); border-top-color: var(--app-text); border-radius: 50%; animation: task-stack-spin .9s linear infinite; }
.task-stack-copy { min-width: 0; display: grid; gap: 1px; text-align: left; }
.task-stack-copy strong, .task-stack-copy small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-stack-copy strong { font-size: 11px; font-weight: 600; }
.task-stack-copy small { color: var(--app-text-muted); font-size: 9px; }
.task-stack-chevron { color: var(--app-text-muted); font-size: 11px; }
.task-stack-popover { width: min(480px, calc(100vw - 32px)); max-height: min(72vh, 680px); overflow: hidden; display: grid; grid-template-rows: auto minmax(0, 1fr); color: var(--app-text); background: var(--app-surface); border: 1px solid var(--app-border); border-radius: 18px; box-shadow: 0 28px 80px color-mix(in srgb, var(--app-text) 18%, transparent); animation: task-popover-in .24s cubic-bezier(.16, 1, .3, 1) both; }
.stack-popover-header { display: flex; align-items: center; justify-content: space-between; padding: 14px 16px; border-bottom: 1px solid var(--app-divider); }
.stack-popover-header > div { display: flex; align-items: baseline; gap: 8px; }
.stack-popover-header strong { font-size: 13px; }
.stack-popover-header small { color: var(--app-text-muted); font-size: 11px; }
.stack-popover-header button { width: 28px; height: 28px; border: 0; border-radius: 50%; color: var(--app-text); background: transparent; font-size: 18px; cursor: pointer; }
.stack-popover-header button:hover { background: var(--app-surface-hover); }
.task-stack-list { overflow-y: auto; }
.task-stack-list :deep(.background-task-card + .background-task-card) { border-top: 1px solid var(--app-divider); }
@keyframes task-stack-spin { to { transform: rotate(360deg); } }
@keyframes task-popover-in { from { opacity: 0; transform: translateY(-7px) scale(.97); } to { opacity: 1; transform: translateY(0) scale(1); } }
</style>
