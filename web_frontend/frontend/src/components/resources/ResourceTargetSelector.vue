<template>
  <div class="resource-target-selector">
    <n-text depth="3" class="resource-target-label">{{ t('resource.configTarget') }}</n-text>
    <n-select
      :value="modelValue"
      :options="selectOptions"
      class="resource-target-select"
      @update:value="(value) => emit('update:modelValue', value)"
    />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NSelect, NText } from 'naive-ui'
import type { SelectGroupOption } from 'naive-ui'
import { useI18n } from '@/composables/useI18n'
import type { ResourceTargetOptionGroup } from '@/types/resourceTarget'

const props = defineProps<{
  modelValue: string
  options: ResourceTargetOptionGroup[]
}>()

const emit = defineEmits<{
  (event: 'update:modelValue', value: string): void
}>()

const { t } = useI18n()
const selectOptions = computed<SelectGroupOption[]>(() => props.options.map(group => ({
  type: 'group',
  label: group.label,
  key: group.key,
  children: group.children.map(option => ({ label: option.label, value: option.value })),
})))
</script>

<style scoped>
.resource-target-selector {
  display: flex;
  align-items: center;
  gap: var(--app-space-sm);
  min-width: 0;
}

.resource-target-label {
  flex: 0 0 auto;
  font-size: var(--app-font-sm);
}

.resource-target-select {
  width: min(280px, 42vw);
}

@media (max-width: 640px) {
  .resource-target-selector {
    width: 100%;
  }

  .resource-target-select {
    flex: 1;
    width: auto;
  }
}
</style>
