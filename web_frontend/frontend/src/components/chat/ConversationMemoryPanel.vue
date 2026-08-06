<template>
  <div class="memory-panel">
    <header>
      <div><strong>{{ t('status.memory') }}</strong><small>{{ memoryActivityText }}</small></div>
      <n-button quaternary circle size="small" :loading="loading" @click="refresh">
        <template #icon><n-icon><RefreshOutline /></n-icon></template>
      </n-button>
    </header>
    <div class="memory-search">
      <n-input v-model:value="query" size="small" clearable :placeholder="t('status.memoryQueryPlaceholder')" @keyup.enter="refresh" />
      <n-button secondary size="small" :loading="loading" @click="refresh">
        <template #icon><n-icon><SearchOutline /></n-icon></template>
      </n-button>
    </div>
    <p v-if="error" class="memory-error">{{ error }}</p>
    <n-spin :show="loading" size="small">
      <n-empty v-if="!items.length && !loading" :description="t('status.memoryEmpty')" size="small" />
      <div v-else class="memory-list">
        <article v-for="item in items" :key="item.memory_id" class="memory-item">
          <div class="memory-item-heading">
            <span>{{ memoryScopeLabel(item.source_scope) }}</span>
            <n-popconfirm
              :positive-text="t('common.delete')"
              :negative-text="t('common.cancel')"
              @positive-click="remove(item)"
            >
              <template #trigger>
                <n-button quaternary circle size="tiny" :loading="Boolean(deleting[item.memory_id])">
                  <template #icon><n-icon><TrashOutline /></n-icon></template>
                </n-button>
              </template>
              {{ t('status.memoryDeleteConfirm') }}
            </n-popconfirm>
          </div>
          <p>{{ item.content }}</p>
          <time v-if="item.updated_at">{{ formatTime(item.updated_at) }}</time>
        </article>
      </div>
    </n-spin>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { NButton, NEmpty, NIcon, NInput, NPopconfirm, NSpin } from 'naive-ui'
import { RefreshOutline, SearchOutline, TrashOutline } from '@/components/icons'
import { memoryApi, type MemoryContextItemView } from '@/api/memory'
import { useI18n } from '@/composables/useI18n'
import { useResourceContext } from '@/composables/useResourceContext'
import { useRuntimeStore } from '@/stores/runtime'

const runtimeStore = useRuntimeStore()
const resourceContext = useResourceContext()
const { t } = useI18n()
const query = ref('')
const items = ref<MemoryContextItemView[]>([])
const loading = ref(false)
const error = ref('')
const deleting = ref<Record<string, boolean>>({})
let requestSerial = 0

const contextKey = computed(() => [
  resourceContext.packageIdForApi.value || '',
  runtimeStore.activeWorkspaceId || '',
].join(':'))
const memoryActivityText = computed(() => {
  const activity = runtimeStore.memoryActivity
  if (activity.status === 'writing') return t('status.memoryWriting')
  if (activity.status === 'failed') return t('status.memoryFailed')
  if (activity.eventType === 'memory_retrieval_completed' || activity.eventType === 'memory_injection_completed') {
    return t('status.memoryRetrieved', { count: Number(activity.payload?.item_count || 0) })
  }
  if (activity.eventType === 'memory_write_completed') return t('status.memoryWriteCompleted')
  return t('status.memoryIdle')
})

async function refresh() {
  const serial = ++requestSerial
  loading.value = true
  error.value = ''
  try {
    const response = await memoryApi.query(
      query.value.trim(),
      resourceContext.packageIdForApi.value,
      8,
      runtimeStore.activeWorkspaceId,
    )
    if (serial === requestSerial) items.value = [...(response.items || [])].sort(memorySort)
  } catch (cause) {
    if (serial === requestSerial) {
      items.value = []
      error.value = cause instanceof Error ? cause.message : String(cause)
    }
  } finally {
    if (serial === requestSerial) loading.value = false
  }
}

async function remove(item: MemoryContextItemView) {
  deleting.value = { ...deleting.value, [item.memory_id]: true }
  try {
    await memoryApi.deleteItem(
      item.memory_id,
      item.source_scope === 'none' ? 'agent' : item.source_scope,
      resourceContext.packageIdForApi.value,
      runtimeStore.activeWorkspaceId,
    )
    items.value = items.value.filter(candidate => candidate.memory_id !== item.memory_id)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  } finally {
    const next = { ...deleting.value }
    delete next[item.memory_id]
    deleting.value = next
  }
}

function memorySort(left: MemoryContextItemView, right: MemoryContextItemView): number {
  return Number(right.score || 0) - Number(left.score || 0)
    || String(right.updated_at || '').localeCompare(String(left.updated_at || ''))
}

function memoryScopeLabel(scope: string): string {
  if (scope === 'workspace') return t('status.memoryScope.workspace')
  if (scope === 'global') return t('status.memoryScope.user')
  return t('status.memoryScope.agent')
}

function formatTime(value: string): string {
  const parsed = new Date(value)
  return Number.isFinite(parsed.getTime())
    ? new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(parsed)
    : value
}

watch(contextKey, () => {
  items.value = []
  void refresh()
}, { immediate: true })
</script>

<style scoped>
.memory-panel { width: min(390px, calc(100vw - 44px)); max-height: min(64vh, 560px); display: flex; flex-direction: column; padding: 14px; }
header, .memory-item-heading, .memory-search { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
header { margin-bottom: 12px; }
header > div { display: grid; gap: 2px; }
header strong { font-size: 13px; }
header small { color: var(--app-text-muted); font-size: 10px; }
.memory-search { margin-bottom: 12px; }
.memory-search :deep(.n-input) { flex: 1; }
.memory-list { display: grid; max-height: 430px; overflow: auto; gap: 8px; padding-right: 3px; }
.memory-item { padding: 10px 11px; border: 1px solid var(--app-border); border-radius: 13px; background: var(--app-surface); }
.memory-item-heading span { color: var(--app-text-muted); font-size: 10px; }
.memory-item p { margin: 6px 0; font-size: 11px; line-height: 1.5; }
.memory-item time { color: var(--app-text-subtle); font-size: 9px; }
.memory-error { color: var(--app-error); font-size: 11px; }
</style>
