<template>
  <div class="scheduler-manager">
    <div class="manager-header">
      <div class="manager-title">
        <n-text strong>{{ t('scheduler.title') }}</n-text>
      </div>
      <div class="manager-controls">
        <ResourceTargetSelector
          v-model="resourceContext.selectedValue.value"
          :options="resourceContext.targetOptions.value"
        />
        <n-button type="primary" @click="showCreateModal = true">
          <template #icon>
            <n-icon><Add /></n-icon>
          </template>
          {{ t('scheduler.createTask') }}
        </n-button>
      </div>
    </div>

    <n-scrollbar class="job-list">
      <div class="job-grid">
        <n-card
          v-for="job in schedulerStore.jobs"
          :key="job.payload?.job_id"
          class="job-card"
        >
          <div class="job-header">
            <div class="job-info">
              <n-text strong>{{ schedulerJobTitle(job) }}</n-text>
              <n-space align="center" :size="8">
                <n-tag :type="getStatusType(job.status)" size="small">
                  {{ schedulerStatusLabel(job.status) }}
                </n-tag>
                <n-tag v-if="!job.enabled" type="default" size="small">
                  {{ t('scheduler.paused') }}
                </n-tag>
              </n-space>
            </div>
            <n-switch
              :value="job.enabled"
              @update:value="(val) => handleToggleEnabled(job, val)"
            />
          </div>

          <n-divider style="margin: 12px 0" />

          <div class="job-schedule">
            <n-icon size="14" class="job-row-icon"><Time /></n-icon>
            <span class="job-row-text job-row-text--mono">{{ job.schedule || t('common.unset') }}</span>
          </div>

          <div v-if="job.targetType" class="job-target">
            <n-icon size="14" class="job-row-icon"><LocateOutline /></n-icon>
            <span class="job-row-text">{{ schedulerTargetLabel(job) }}</span>
          </div>

          <div class="job-actions">
            <n-button size="small" @click="handleRunNow(job)">
              {{ t('scheduler.runNow') }}
            </n-button>
            <n-button size="small" @click="handleViewHistory(job)">
              {{ t('scheduler.history') }}
            </n-button>
            <n-dropdown
              :options="getJobActions()"
              @select="(key) => handleAction(key, job)"
            >
              <n-button size="small" quaternary circle>
                <n-icon><EllipsisHorizontal /></n-icon>
              </n-button>
            </n-dropdown>
          </div>
        </n-card>
      </div>

      <n-empty
        v-if="schedulerStore.jobs.length === 0"
        :description="t('scheduler.empty')"
        class="manager-empty"
      >
        <template #icon>
          <n-icon size="56" class="manager-empty-icon">
            <Time />
          </n-icon>
        </template>
        <template #extra>
          <n-button type="primary" @click="showCreateModal = true">{{ t('scheduler.createFirst') }}</n-button>
        </template>
      </n-empty>
    </n-scrollbar>

    <!-- 创建任务弹窗 -->
    <SchedulerJobFormModal
      v-model:show="showCreateModal"
      @submit="handleCreate"
    />

    <!-- 运行历史抽屉 -->
    <SchedulerHistoryDrawer
      v-model:show="showHistoryDrawer"
      :job-id="selectedJobId"
      :package-id="resourceContext.packageIdForApi.value"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { NText, NButton, NIcon, NScrollbar, NCard, NTag, NSpace, NSwitch, NDivider, NDropdown, NEmpty, useDialog } from 'naive-ui'
import { Add, Time, LocateOutline, EllipsisHorizontal } from '@/components/icons'
import { useSchedulerStore } from '@/stores/scheduler'
import { useCommand } from '@/composables/useCommand'
import { useI18n } from '@/composables/useI18n'
import { useManagedResourceContext } from '@/composables/useManagedResourceContext'
import ResourceTargetSelector from '@/components/resources/ResourceTargetSelector.vue'
import SchedulerJobFormModal from './SchedulerJobFormModal.vue'
import SchedulerHistoryDrawer from './SchedulerHistoryDrawer.vue'
import type { SchedulerJobView } from '@/types/protocol'

const schedulerStore = useSchedulerStore()
const commands = useCommand()
const dialog = useDialog()
const resourceContext = useManagedResourceContext('package_only')
const { t } = useI18n()
const showCreateModal = ref(false)
const showHistoryDrawer = ref(false)
const selectedJobId = ref<string | null>(null)

function handleToggleEnabled(job: SchedulerJobView, enabled: boolean) {
  const jobId = job.payload?.job_id
  if (!jobId) return

  if (enabled) {
    commands.resumeJob(jobId, resourceContext.packageIdForApi.value)
  } else {
    commands.pauseJob(jobId, resourceContext.packageIdForApi.value)
  }
}

function handleRunNow(job: SchedulerJobView) {
  const jobId = job.payload?.job_id
  if (jobId) {
    commands.runJobNow(jobId, resourceContext.packageIdForApi.value)
  }
}

function handleViewHistory(job: SchedulerJobView) {
  selectedJobId.value = job.payload?.job_id || null
  showHistoryDrawer.value = true
}

function handleCreate(jobData: any) {
  commands.createSchedulerJob(jobData, resourceContext.packageIdForApi.value)
  showCreateModal.value = false
}

function handleAction(key: string, job: SchedulerJobView) {
  const jobId = job.payload?.job_id
  if (!jobId) return

  switch (key) {
    case 'delete':
      dialog.warning({
        title: t('scheduler.deleteTitle'),
        content: t('scheduler.deleteContent', { name: schedulerJobTitle(job) }),
        positiveText: t('common.delete'),
        negativeText: t('common.cancel'),
        positiveButtonProps: { type: 'error' },
        onPositiveClick: () => {
          commands.deleteJob(jobId, resourceContext.packageIdForApi.value)
        },
      })
      break
  }
}

function getJobActions() {
  return [
    { label: t('common.delete'), key: 'delete' },
  ]
}

function schedulerStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    scheduled: t('scheduler.status.scheduled'),
    running: t('scheduler.status.running'),
    completed: t('scheduler.status.completed'),
    failed: t('scheduler.status.failed'),
    skipped: t('scheduler.status.skipped'),
    cancelled: t('scheduler.status.cancelled'),
    enabled: t('scheduler.status.enabled'),
    paused: t('scheduler.status.paused'),
  }
  return labels[status] || status || t('common.unknown')
}

function schedulerJobTitle(job: SchedulerJobView): string {
  return job.title || t('scheduler.title')
}

function schedulerTargetLabel(job: SchedulerJobView): string {
  const payload = job.payload?.target?.payload || {}
  if (job.targetType === 'script_run') return t('scheduler.targetScript')
  if (job.targetType === 'tool_call') {
    return t('scheduler.targetToolWithName', { name: payload.tool_id || t('scheduler.targetUnselectedTool') })
  }
  if (job.targetType === 'graph_run') return t('scheduler.targetGraph')
  return job.targetLabel || job.targetType || t('scheduler.title')
}

function getStatusType(status: string): 'default' | 'success' | 'warning' | 'error' | 'info' {
  const types: Record<string, any> = {
    ready: 'success',
    enabled: 'success',
    scheduled: 'info',
    running: 'info',
    completed: 'success',
    failed: 'error',
    paused: 'default',
    skipped: 'warning',
    cancelled: 'warning',
  }
  return types[status] || 'default'
}

onMounted(() => {
  commands.listAgentPackages()
  refreshCurrentScheduler()
})

watch(
  () => resourceContext.workspaceContextKey.value,
  () => {
    refreshCurrentScheduler()
  }
)

function refreshCurrentScheduler() {
  const packageId = resourceContext.packageIdForApi.value
  schedulerStore.reset()
  selectedJobId.value = null
  showHistoryDrawer.value = false
  commands.refreshSchedulerOptions(packageId)
  commands.refreshScheduler(packageId)
}
</script>

<style scoped>
.scheduler-manager {
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: var(--app-space-xl);
  max-width: var(--app-content-max-width);
  width: 100%;
  margin: 0 auto;
}

.manager-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-md);
  margin-bottom: var(--app-space-xl);
  flex-wrap: wrap;
}

.manager-title {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-xs);
  min-width: 0;
}

.manager-controls {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--app-space-md);
  flex-wrap: wrap;
}

.job-list {
  flex: 1;
  min-height: 0;
  margin: 0 calc(var(--app-space-xs) * -1);
  padding: 0 var(--app-space-xs) var(--app-space-lg);
}

.job-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: var(--app-space-lg);
}

.job-card {
  transition: transform var(--app-transition-spring), box-shadow var(--app-transition-base);
  border-radius: var(--app-radius-lg);
  animation: app-fade-in-up 0.5s var(--app-transition-spring) both;
  will-change: transform;
}

.job-card:nth-child(1) { animation-delay: 0.08s; }
.job-card:nth-child(2) { animation-delay: 0.16s; }
.job-card:nth-child(3) { animation-delay: 0.24s; }
.job-card:nth-child(4) { animation-delay: 0.32s; }
.job-card:nth-child(5) { animation-delay: 0.40s; }
.job-card:nth-child(n+6) { animation-delay: 0.48s; }

.job-card:hover {
  transform: translateY(-4px);
  box-shadow: var(--app-shadow-lg);
}

.job-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--app-space-md);
}

.job-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: var(--app-space-sm);
  min-width: 0;
}

.job-schedule,
.job-target {
  display: flex;
  align-items: center;
  gap: var(--app-space-sm);
  margin: var(--app-space-sm) 0;
  min-width: 0;
}

.job-row-icon {
  flex-shrink: 0;
  color: var(--app-text-muted);
}

.job-row-text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--app-font-sm);
  color: var(--app-text-secondary);
  line-height: 1.4;
}

.job-row-text--mono {
  font-family: 'SF Mono', Monaco, 'Cascadia Code', 'Roboto Mono', monospace;
  font-size: var(--app-font-xs);
  color: var(--app-text);
  background: var(--app-surface-muted);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  padding: 2px 6px;
}

.job-actions {
  display: flex;
  gap: var(--app-space-sm);
  margin-top: var(--app-space-md);
  flex-wrap: wrap;
}

.manager-empty {
  margin-top: 12vh;
  animation: app-fade-in-up 0.4s cubic-bezier(0.16, 1, 0.3, 1) both;
}

.manager-empty-icon {
  display: block;
  color: var(--app-text-muted);
  opacity: 0.55;
  line-height: 1;
}

@media (max-width: 640px) {
  .scheduler-manager {
    padding: var(--app-space-md);
  }
  .job-grid {
    grid-template-columns: 1fr;
    gap: var(--app-space-md);
  }
}
</style>
