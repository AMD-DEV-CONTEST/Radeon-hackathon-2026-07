<template>
  <n-modal
    v-model:show="show"
    preset="card"
    :title="t('scheduler.createTitle')"
    style="width: min(720px, calc(100vw - 32px))"
  >
    <n-form ref="formRef" :model="formData" :rules="rules" label-placement="top">
      <n-grid :cols="2" :x-gap="16">
        <n-form-item-gi :label="t('scheduler.targetKind')" path="target_kind">
          <n-select v-model:value="formData.target_kind" :options="targetOptions" />
        </n-form-item-gi>

        <n-form-item-gi :label="t('scheduler.enabled')">
          <n-switch v-model:value="formData.enabled" />
        </n-form-item-gi>
      </n-grid>

      <n-form-item v-if="formData.target_kind === 'tool_call'" :label="t('scheduler.tool')" path="tool_id">
        <n-select
          v-model:value="formData.tool_id"
          :options="toolOptions"
          filterable
          :placeholder="t('scheduler.toolPlaceholder')"
        />
      </n-form-item>

      <n-form-item :label="t('scheduler.cron')" path="schedule_expr">
        <n-input v-model:value="formData.schedule_expr" placeholder="0 9 * * *" />
      </n-form-item>

      <n-form-item :label="t('scheduler.task')" path="task_content">
        <n-input
          v-model:value="formData.task_content"
          type="textarea"
          :rows="3"
          :placeholder="t('scheduler.taskPlaceholder')"
        />
      </n-form-item>

      <n-form-item v-if="formData.target_kind === 'script_run'" :label="t('scheduler.scriptCommand')" path="command">
        <n-input
          v-model:value="formData.command"
          type="textarea"
          :rows="4"
          :placeholder="t('scheduler.scriptCommandPlaceholder')"
        />
      </n-form-item>

      <section v-if="formData.target_kind === 'tool_call'" class="tool-arguments-section">
        <div class="tool-arguments-header">
          <div>
            <div class="tool-arguments-title">{{ t('scheduler.toolArguments') }}</div>
            <div v-if="selectedTool?.description" class="tool-description">
              {{ selectedTool.description }}
            </div>
          </div>
          <n-radio-group
            :value="argumentMode"
            size="small"
            class="soft-segmented-control"
            @update:value="handleArgumentModeChange"
          >
            <n-radio-button value="form">{{ t('scheduler.argumentForm') }}</n-radio-button>
            <n-radio-button value="json">{{ t('scheduler.argumentJson') }}</n-radio-button>
          </n-radio-group>
        </div>

        <n-alert v-if="argumentError" type="error" :show-icon="false">
          {{ argumentError }}
        </n-alert>

        <ResourceSchemaForm
          v-if="argumentMode === 'form' && selectedToolSchema"
          v-model="argumentDraft"
          :schema="selectedToolSchema"
          :show-validation="argumentValidationVisible"
        />
        <n-empty
          v-else-if="argumentMode === 'form'"
          :description="t('scheduler.noToolSchema')"
          size="small"
        />
        <n-input
          v-else
          v-model:value="formData.arguments_json"
          type="textarea"
          :rows="6"
          placeholder="{ }"
        />
      </section>

    </n-form>

    <template #footer>
      <n-space justify="end">
        <n-button @click="show = false">{{ t('common.cancel') }}</n-button>
        <n-button type="primary" @click="handleSubmit">{{ t('scheduler.create') }}</n-button>
      </n-space>
    </template>
  </n-modal>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  NAlert,
  NButton,
  NEmpty,
  NForm,
  NFormItem,
  NFormItemGi,
  NGrid,
  NInput,
  NModal,
  NRadioButton,
  NRadioGroup,
  NSelect,
  NSpace,
  NSwitch,
} from 'naive-ui'
import type { FormInst, FormRules } from 'naive-ui'
import { useSchedulerStore } from '@/stores/scheduler'
import type { SchedulerJobInput } from '@/api/resourceTypes'
import { useI18n } from '@/composables/useI18n'
import { requiredTextRule } from '@/utils/formValidation'
import ResourceSchemaForm from '@/components/agent/ResourceSchemaForm.vue'
import {
  createResourceDraft,
  resourceDraftComplete,
  resourceDraftValue,
} from '@/components/agent/resourceSchema'

type TargetKind = 'graph_run' | 'script_run' | 'tool_call'

const props = defineProps<{
  show: boolean
}>()

const emit = defineEmits<{
  'update:show': [value: boolean]
  submit: [data: SchedulerJobInput]
}>()

const show = computed({
  get: () => props.show,
  set: (value) => emit('update:show', value),
})

const schedulerStore = useSchedulerStore()
const { t } = useI18n()
const formRef = ref<FormInst | null>(null)
const argumentMode = ref<'form' | 'json'>('form')
const argumentDraft = ref<unknown>({})
const argumentError = ref('')
const argumentValidationVisible = ref(false)
const formData = ref({
  target_kind: 'graph_run' as TargetKind,
  enabled: true,
  tool_id: null as string | null,
  schedule_expr: '0 9 * * *',
  task_content: '',
  command: '',
  arguments_json: '{}',
})

const targetOptions = computed(() => [
  { label: t('scheduler.targetGraph'), value: 'graph_run' },
  { label: t('scheduler.targetScript'), value: 'script_run' },
  { label: t('scheduler.targetTool'), value: 'tool_call' },
])

const toolOptions = computed(() => (
  schedulerStore.toolOptions.map((tool) => ({
    label: tool.description ? `${tool.name} - ${tool.description}` : tool.name,
    value: tool.id,
  }))
))

const selectedTool = computed(() => (
  schedulerStore.toolOptions.find(tool => tool.id === formData.value.tool_id) || null
))

const selectedToolSchema = computed<Record<string, unknown> | null>(() => {
  const schema = selectedTool.value?.inputSchema
  return schema && typeof schema === 'object' && !Array.isArray(schema) ? schema : null
})

const rules = computed<FormRules>(() => ({
  schedule_expr: [requiredTextRule(t('scheduler.validateCron'))],
  task_content: [requiredTextRule(t('scheduler.validateTask'))],
  tool_id: [
    {
      required: formData.value.target_kind === 'tool_call',
      validator: () => formData.value.target_kind !== 'tool_call' || Boolean(formData.value.tool_id),
      message: t('scheduler.validateTool'),
      trigger: 'change',
    },
  ],
  command: [
    {
      required: formData.value.target_kind === 'script_run',
      validator: () => formData.value.target_kind !== 'script_run' || Boolean(formData.value.command.trim()),
      message: t('scheduler.validateCommand'),
      trigger: ['input', 'blur'],
    },
  ],
}))

function handleSubmit() {
  formRef.value?.validate((errors) => {
    if (errors) return
    const jobInput = buildJobInput()
    if (!jobInput) return
    emit('submit', jobInput)
    resetForm()
  })
}

function buildJobInput(): SchedulerJobInput | null {
  const base = {
    task_content: formData.value.task_content.trim(),
    schedule_type: 'cron' as const,
    schedule_expr: formData.value.schedule_expr.trim(),
    enabled: formData.value.enabled,
  }

  if (formData.value.target_kind === 'script_run') {
    return {
      ...base,
      target: {
        target_type: 'script_run',
        payload: { command: formData.value.command.trim() },
      },
    }
  }

  if (formData.value.target_kind === 'tool_call') {
    const parsedArguments = toolArguments()
    if (parsedArguments === null) return null
    return {
      ...base,
      target: {
        target_type: 'tool_call',
        payload: {
          tool_id: formData.value.tool_id || '',
          arguments: parsedArguments,
        },
      },
    }
  }

  const payload = {
    message: formData.value.task_content.trim(),
  }
  return {
    ...base,
    target: {
      target_type: 'graph_run',
      payload,
    },
  }
}

function toolArguments(): Record<string, any> | null {
  argumentError.value = ''
  if (argumentMode.value === 'json') return parseArguments()
  const schema = selectedToolSchema.value
  if (!schema) return {}
  if (!resourceDraftComplete(schema, argumentDraft.value)) {
    argumentValidationVisible.value = true
    argumentError.value = t('scheduler.invalidToolArguments')
    return null
  }
  const value = resourceDraftValue(schema, argumentDraft.value)
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    argumentError.value = t('scheduler.invalidToolArguments')
    return null
  }
  return value as Record<string, any>
}

function parseArguments(): Record<string, any> | null {
  const raw = formData.value.arguments_json.trim()
  if (!raw) return {}
  try {
    const parsed = JSON.parse(raw)
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) return parsed
  } catch {
    // The error below is shared by syntax and top-level type failures.
  }
  argumentError.value = t('scheduler.invalidToolArgumentsJson')
  return null
}

function handleArgumentModeChange(value: string): void {
  if (value !== 'form' && value !== 'json') return
  argumentError.value = ''
  argumentValidationVisible.value = false
  if (value === 'json') {
    const schema = selectedToolSchema.value
    const current = schema ? resourceDraftValue(schema, argumentDraft.value) : {}
    formData.value.arguments_json = JSON.stringify(current, null, 2)
  } else {
    argumentDraft.value = createResourceDraft(selectedToolSchema.value || { type: 'object', properties: {} }, parsedJsonArguments())
  }
  argumentMode.value = value
}

function parsedJsonArguments(): Record<string, unknown> | undefined {
  try {
    const parsed = JSON.parse(formData.value.arguments_json || '{}')
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
      ? parsed as Record<string, unknown>
      : undefined
  } catch {
    return undefined
  }
}

function resetForm() {
  formData.value = {
    target_kind: 'graph_run',
    enabled: true,
    tool_id: null,
    schedule_expr: '0 9 * * *',
    task_content: '',
    command: '',
    arguments_json: '{}',
  }
  argumentMode.value = 'form'
  argumentDraft.value = {}
  argumentError.value = ''
  argumentValidationVisible.value = false
}

watch(
  () => formData.value.tool_id,
  () => {
    argumentDraft.value = createResourceDraft(selectedToolSchema.value || { type: 'object', properties: {} })
    formData.value.arguments_json = '{}'
    argumentError.value = ''
    argumentValidationVisible.value = false
  },
)

watch(
  () => props.show,
  visible => {
    if (!visible) return
    argumentDraft.value = createResourceDraft(selectedToolSchema.value || { type: 'object', properties: {} })
    argumentError.value = ''
  },
)
</script>

<style scoped>
.tool-arguments-section {
  display: grid;
  gap: var(--app-space-md);
  margin-bottom: var(--app-space-lg);
}

.tool-arguments-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--app-space-lg);
}

.tool-arguments-title {
  color: var(--app-text-primary);
  font-size: var(--app-font-sm);
  font-weight: 500;
}

.tool-description {
  margin-top: var(--app-space-xs);
  color: var(--app-text-muted);
  font-size: var(--app-font-xs);
}

@media (max-width: 640px) {
  .tool-arguments-header {
    flex-direction: column;
  }
}
</style>
