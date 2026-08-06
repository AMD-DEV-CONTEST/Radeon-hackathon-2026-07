<template>
  <span class="setting-help-label">
    <span>{{ label }}</span>
    <n-tooltip v-if="help" trigger="hover">
      <template #trigger>
        <n-icon class="setting-help-icon" :component="InformationCircleOutline" />
      </template>
      <span class="setting-help-content">{{ help }}</span>
    </n-tooltip>
  </span>
</template>

<script setup lang="ts">
import { NIcon, NTooltip } from 'naive-ui'
import { InformationCircleOutline } from '@vicons/ionicons5'

defineProps<{
  label: string
  help?: string
}>()
</script>

<style scoped>
.setting-help-label {
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-xs);
  min-width: 0;
}

.setting-help-icon {
  flex: none;
  color: var(--app-text-muted);
  cursor: help;
  font-size: 16px;
}

.setting-help-content {
  display: inline-block;
  max-width: 280px;
  line-height: 1.5;
}
</style>
