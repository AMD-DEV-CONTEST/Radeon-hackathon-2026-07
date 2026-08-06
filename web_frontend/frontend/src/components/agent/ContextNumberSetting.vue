<template>
  <div class="context-number-setting">
    <setting-help-label :label="label" :help="help" />
    <n-input-number
      :value="modelValue"
      :min="min"
      :max="max"
      :step="step"
      :precision="precision"
      :disabled="disabled"
      @update:value="updateValue"
    />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NInputNumber } from 'naive-ui'
import SettingHelpLabel from './SettingHelpLabel.vue'

const props = withDefaults(defineProps<{
  modelValue: number
  label: string
  help?: string
  min: number
  max: number
  step?: number
  disabled?: boolean
}>(), {
  step: 1,
  disabled: false,
})

const emit = defineEmits<{
  'update:modelValue': [value: number]
}>()

const precision = computed(() => props.step < 1 ? 2 : 0)

function updateValue(value: number | null): void {
  if (value !== null) emit('update:modelValue', value)
}
</script>

<style scoped>
.context-number-setting {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.context-number-setting :deep(.n-input-number) {
  width: 150px;
}
</style>
