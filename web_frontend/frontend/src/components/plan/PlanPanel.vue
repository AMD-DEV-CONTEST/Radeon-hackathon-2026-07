<template>
  <div v-if="runtimeStore.currentPlan" class="plan-panel" :class="{ compact }">
    <div class="plan-header">
      <n-text strong>{{ runtimeStore.currentPlan.goal }}</n-text>
      <n-tag :type="planStatusType" size="small">
        {{ runtimeStore.currentPlan.status }}
      </n-tag>
    </div>

    <div class="plan-steps">
      <div
        v-for="step in runtimeStore.currentPlan.steps"
        :key="step.step_id"
        class="plan-step"
        :class="[`status-${step.status}`]"
      >
        <div class="step-header">
          <n-icon :component="stepIcon(step.status)" />
          <span class="step-title">{{ step.title }}</span>
        </div>
        <div v-if="!compact && step.objective" class="step-objective">
          {{ step.objective }}
        </div>
        <div v-if="step.result_summary" class="step-result">
          {{ step.result_summary }}
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NText, NTag, NIcon } from 'naive-ui'
import { CheckmarkCircle, CloseCircle, EllipseOutline, TimeOutline } from '@/components/icons'
import { useRuntimeStore } from '@/stores/runtime'
import type { PlanStepStatus } from '@/types/protocol'

defineProps<{
  compact?: boolean
}>()

const runtimeStore = useRuntimeStore()

const planStatusType = computed(() => {
  const status = runtimeStore.currentPlan?.status
  if (!status) return 'default'
  if (status.includes('completed')) return 'success'
  if (status.includes('failed')) return 'error'
  if (status.includes('running')) return 'info'
  return 'default'
})

function stepIcon(status: PlanStepStatus) {
  const icons = {
    pending: EllipseOutline,
    in_progress: TimeOutline,
    completed: CheckmarkCircle,
    failed: CloseCircle,
    skipped: EllipseOutline,
  }
  return icons[status] || EllipseOutline
}
</script>

<style scoped>
.plan-panel {
  padding: var(--app-space-lg);
  background: var(--app-surface-muted);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
}

.plan-panel.compact {
  padding: var(--app-space-md);
}

.plan-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-sm);
  margin-bottom: var(--app-space-md);
}

.plan-steps {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-sm);
}

.plan-step {
  padding: var(--app-space-md);
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  border-left: 3px solid var(--app-border);
  transition: border-color var(--app-transition-fast);
  animation: app-fade-in-up 0.24s cubic-bezier(0.16, 1, 0.3, 1) both;
}

.plan-step.status-in_progress {
  border-left-color: var(--app-info);
}

.plan-step.status-completed {
  border-left-color: var(--app-success);
  opacity: 0.72;
}

.plan-step.status-failed {
  border-left-color: var(--app-error);
}

.step-header {
  display: flex;
  align-items: center;
  gap: var(--app-space-sm);
  font-weight: 600;
  color: var(--app-text);
}

.step-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.step-objective,
.step-result {
  margin-top: var(--app-space-xs);
  font-size: var(--app-font-md);
  color: var(--app-text-secondary);
  line-height: var(--app-leading-normal);
}

.step-result {
  font-style: italic;
}
</style>
