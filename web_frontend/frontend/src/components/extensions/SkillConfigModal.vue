<template>
  <n-modal v-model:show="show" preset="card" :title="modalTitle" style="width: 560px">
    <n-form ref="formRef" :model="formData" :rules="rules">
      <n-form-item :label="t('extensions.skillPath')" path="path">
        <n-input-group>
          <n-input
            v-model:value="formData.path"
            :placeholder="t('extensions.selectSkillFolderHint')"
            readonly
          />
          <n-button
            :disabled="formData.source !== 'local'"
            :loading="selectingDirectory"
            @click="handleSelectDirectory"
          >
            {{ t('extensions.selectSkillFolder') }}
          </n-button>
        </n-input-group>
      </n-form-item>

      <n-form-item :label="t('extensions.source')">
        <n-select v-model:value="formData.source" :options="sourceOptions" />
      </n-form-item>

    </n-form>

    <template #footer>
      <n-space justify="end">
        <n-button @click="show = false">{{ t('common.cancel') }}</n-button>
        <n-button type="primary" @click="handleSubmit">{{ submitText }}</n-button>
      </n-space>
    </template>
  </n-modal>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { NButton, NForm, NFormItem, NInput, NInputGroup, NModal, NSelect, NSpace, useMessage } from 'naive-ui'
import type { FormInst, FormRules } from 'naive-ui'
import type { SkillConfig } from '@/api/resourceTypes'
import type { ExtensionItemView } from '@/types/protocol'
import { selectLocalDirectory } from '@/api/desktopDialogs'
import { useI18n } from '@/composables/useI18n'
import { requiredTextRule } from '@/utils/formValidation'

const props = defineProps<{
  show: boolean
  item?: ExtensionItemView | null
}>()

const emit = defineEmits<{
  'update:show': [value: boolean]
  submit: [data: SkillConfig]
}>()

interface SkillFormData {
  path: string
  source: string
  required: boolean
}

const show = computed({
  get: () => props.show,
  set: (value) => emit('update:show', value),
})

const formRef = ref<FormInst | null>(null)
const formData = ref<SkillFormData>(emptyForm())
const { t } = useI18n()
const message = useMessage()
const selectingDirectory = ref(false)
const modalTitle = computed(() => (props.item ? t('extensions.skillEditTitle') : t('extensions.skillAddTitle')))
const submitText = computed(() => (props.item ? t('common.save') : t('common.add')))

const sourceOptions = computed(() => {
  const options = [{ label: t('extensions.local'), value: 'local' }]
  if (formData.value.source && formData.value.source !== 'local') {
    options.push({ label: formData.value.source, value: formData.value.source })
  }
  return options
})

const rules = computed<FormRules>(() => ({
  path: [requiredTextRule(t('extensions.validateSkillPath'))],
}))

function emptyForm(): SkillFormData {
  return {
    path: '',
    source: 'local',
    required: false,
  }
}

function loadForm(item: ExtensionItemView | null | undefined): void {
  if (!item) {
    formData.value = emptyForm()
    return
  }
  const payload = item.payload || {}
  formData.value = {
    path: String(payload.path || ''),
    source: String(payload.source || 'local'),
    required: Boolean(payload.required),
  }
}

watch(
  () => props.show,
  (visible) => {
    if (visible) loadForm(props.item)
  }
)

watch(
  () => props.item,
  (item) => {
    if (props.show) loadForm(item)
  }
)

async function handleSelectDirectory(): Promise<void> {
  selectingDirectory.value = true
  try {
    const selected = await selectLocalDirectory(formData.value.path)
    if (selected) {
      formData.value.path = selected
      await formRef.value?.validate()
    }
  } catch (error) {
    message.error(t('extensions.selectSkillFolderFailed', {
      reason: error instanceof Error ? error.message : String(error),
    }))
  } finally {
    selectingDirectory.value = false
  }
}

function handleSubmit(): void {
  formRef.value?.validate((errors) => {
    if (errors) return
    emit('submit', {
      path: formData.value.path.trim(),
      source: formData.value.source,
      enabled: true,
      required: formData.value.required,
      replace_skill_id: props.item?.payload?.skill_id,
    })
  })
}
</script>
