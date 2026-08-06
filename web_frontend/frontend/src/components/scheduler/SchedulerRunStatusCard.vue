<template>
  <n-card class="scheduler-run-card" size="small" :bordered="true">
    <div class="card-row">
      <div class="status-icon" :class="`status-icon--${statusTone}`">
        <n-spin v-if="isActive" :size="18" />
        <n-icon v-else :size="18"><Time /></n-icon>
      </div>
      <div class="card-content">
        <div class="card-heading">
          <n-text strong>{{ notice.title }}</n-text>
          <n-tag :type="statusTagType" size="small" round>{{ statusLabel }}</n-tag>
        </div>
        <n-text depth="3" class="card-summary">{{ notice.summary }}</n-text>
        <n-text depth="3" class="card-time">{{ formattedTime }}</n-text>
      </div>
      <div class="card-actions">
        <n-button size="tiny" quaternary @click="$emit('details')">{{ t('scheduler.viewDetails') }}</n-button>
        <n-button
          v-if="dismissible"
          size="tiny"
          quaternary
          circle
          :title="t('common.close')"
          :aria-label="t('common.close')"
          @click="$emit('dismiss')"
        >
          <template #icon><n-icon><Close /></n-icon></template>
        </n-button>
      </div>
    </div>
  </n-card>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NButton, NCard, NIcon, NSpin, NTag, NText } from 'naive-ui'
import { Close, Time } from '@/components/icons'
import { useI18n } from '@/composables/useI18n'
import type { SchedulerRunNoticeView } from '@/types/protocol'

const props = withDefaults(defineProps<{
  notice: SchedulerRunNoticeView
  dismissible?: boolean
}>(), {
  dismissible: false,
})

defineEmits<{
  details: []
  dismiss: []
}>()

const { locale, t } = useI18n()
const isActive = computed(() => ['scheduled', 'pending', 'running'].includes(props.notice.status))
const statusTone = computed(() => {
  if (isActive.value) return 'active'
  if (props.notice.status === 'completed') return 'success'
  if (props.notice.status === 'skipped' || props.notice.status === 'cancelled') return 'warning'
  return 'error'
})
const statusTagType = computed<'default' | 'success' | 'warning' | 'error' | 'info'>(() => {
  if (isActive.value) return 'info'
  if (props.notice.status === 'completed') return 'success'
  if (props.notice.status === 'skipped' || props.notice.status === 'cancelled') return 'warning'
  return 'error'
})
const statusLabel = computed(() => {
  const keyByStatus = {
    scheduled: 'scheduler.status.scheduled',
    pending: 'scheduler.status.scheduled',
    running: 'scheduler.status.running',
    completed: 'scheduler.status.completed',
    failed: 'scheduler.status.failed',
    skipped: 'scheduler.status.skipped',
    cancelled: 'scheduler.status.cancelled',
  } as const
  return t(keyByStatus[props.notice.status as keyof typeof keyByStatus] || 'scheduler.status.updated')
})
const formattedTime = computed(() => {
  const date = new Date(props.notice.timestamp)
  return isNaN(date.getTime()) ? props.notice.timestamp : date.toLocaleString(locale.value)
})
</script>

<style scoped>
.scheduler-run-card {
  width: min(100%, 720px);
  margin: var(--app-space-sm) auto;
  background: color-mix(in srgb, var(--app-surface) 92%, var(--app-info) 8%);
}

.card-row {
  display: flex;
  align-items: flex-start;
  gap: var(--app-space-md);
}

.status-icon {
  width: 32px;
  height: 32px;
  flex: 0 0 32px;
  border-radius: 50%;
  display: grid;
  place-items: center;
  background: var(--app-surface-muted);
}

.status-icon--active { color: var(--app-info); }
.status-icon--success { color: var(--app-success); }
.status-icon--warning { color: var(--app-warning); }
.status-icon--error { color: var(--app-error); }

.card-content {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.card-heading {
  display: flex;
  align-items: center;
  gap: var(--app-space-sm);
  flex-wrap: wrap;
}

.card-summary {
  overflow-wrap: anywhere;
}

.card-time {
  font-size: 12px;
}

.card-actions {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 2px;
}

@media (max-width: 680px) {
  .card-row { flex-wrap: wrap; }
  .card-actions { width: 100%; justify-content: flex-end; }
}
</style>
