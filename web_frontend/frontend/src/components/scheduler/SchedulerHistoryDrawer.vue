<template>
  <n-drawer v-model:show="show" :width="400" placement="right">
    <n-drawer-content>
      <template #header>
        <div class="drawer-header">
          <span>{{ t('scheduler.history') }}</span>
          <n-button size="small" @click="refreshRuns">{{ t('common.refresh') }}</n-button>
        </div>
      </template>

      <n-list bordered>
        <n-list-item v-for="run in runs" :key="run.run_id">
          <n-thing>
            <template #header>
              <n-tag :type="getRunStatusType(run.status)" size="small">
                {{ runStatusLabel(run.status) }}
              </n-tag>
            </template>
            <template #description>
              <div class="run-description">
                <n-text depth="3" style="font-size: 12px">
                  {{ formatTime(run.started_at || run.scheduled_at) }}
                </n-text>
                <n-text v-if="run.output_summary || run.error_summary" depth="2" style="font-size: 12px">
                  {{ run.output_summary || run.error_summary }}
                </n-text>
              </div>
            </template>
          </n-thing>
        </n-list-item>
      </n-list>

      <n-empty
        v-if="runs.length === 0"
        :description="t('scheduler.noRuns')"
        size="small"
        style="margin-top: 40px"
      />
    </n-drawer-content>
  </n-drawer>
</template>

<script setup lang="ts">
import { computed, watch } from 'vue'
import { NButton, NDrawer, NDrawerContent, NList, NListItem, NThing, NTag, NText, NEmpty } from 'naive-ui'
import { useSchedulerStore } from '@/stores/scheduler'
import { useCommand } from '@/composables/useCommand'
import { useI18n } from '@/composables/useI18n'

const props = defineProps<{
  show: boolean
  jobId: string | null
  packageId?: string | null
}>()

const emit = defineEmits<{
  'update:show': [value: boolean]
}>()

const schedulerStore = useSchedulerStore()
const commands = useCommand()
const { locale, t } = useI18n()

const show = computed({
  get: () => props.show,
  set: (value) => emit('update:show', value),
})

const runs = computed(() => schedulerStore.runs)

watch(
  () => [props.show, props.jobId, props.packageId] as const,
  ([visible, jobId, packageId]) => {
    if (visible && jobId) {
      schedulerStore.selectJob(jobId)
      void commands.listSchedulerRuns(jobId, 50, packageId || undefined)
    }
  },
  { immediate: true }
)

function refreshRuns() {
  if (props.jobId) {
    void commands.listSchedulerRuns(props.jobId, 50, props.packageId || undefined)
  }
}

function getRunStatusType(status: string): 'default' | 'success' | 'error' | 'info' {
  const types: Record<string, any> = {
    completed: 'success',
    failed: 'error',
    running: 'info',
  }
  return types[status] || 'default'
}

function runStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    completed: t('scheduler.status.completed'),
    failed: t('scheduler.status.failed'),
    running: t('scheduler.status.running'),
    skipped: t('scheduler.status.skipped'),
    cancelled: t('scheduler.status.cancelled'),
  }
  return labels[status] || status || t('common.unknown')
}

function formatTime(timestamp: string): string {
  if (!timestamp) return t('time.notStarted')
  const date = new Date(timestamp)
  if (isNaN(date.getTime())) return timestamp
  return date.toLocaleString(locale.value)
}
</script>

<style scoped>
.drawer-header {
  display: flex;
  width: 100%;
  align-items: center;
  justify-content: space-between;
}

.run-description {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
</style>
