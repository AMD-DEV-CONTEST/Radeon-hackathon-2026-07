<template>
  <div v-if="fields" class="resource-schema-form">
    <label
      v-for="field in fields"
      :key="field.name"
      class="resource-field"
      :class="{ 'resource-field-invalid': fieldInvalid(field) }"
    >
      <span class="resource-field-label">
        {{ field.schema.title || field.name }}
        <span v-if="field.required" class="required-mark">*</span>
      </span>
      <n-select
        v-if="field.schema.enum?.length"
        :value="enumFieldValue(field.name)"
        :options="enumOptions(field.schema.enum)"
        clearable
        size="small"
        :status="fieldInvalid(field) ? 'error' : undefined"
        :placeholder="fieldPlaceholder(field)"
        @update:value="setFieldValue(field.name, $event)"
      />
      <ResourceSchemaForm
        v-else-if="field.schema.type === 'object'"
        :model-value="fieldValue(field.name)"
        :schema="schemaRecord(field.schema)"
        :secret-fields="childSecretFields(field.name)"
        :show-validation="showValidation"
        class="nested-resource-form"
        @update:model-value="setFieldValue(field.name, $event)"
      />
      <n-input-number
        v-else-if="field.schema.type === 'integer' || field.schema.type === 'number'"
        :value="numberFieldValue(field.name)"
        :min="field.schema.minimum"
        :max="field.schema.maximum"
        :precision="field.schema.type === 'integer' ? 0 : undefined"
        :show-button="false"
        size="small"
        :status="fieldInvalid(field) ? 'error' : undefined"
        :placeholder="fieldPlaceholder(field)"
        @update:value="setFieldValue(field.name, $event)"
      />
      <n-select
        v-else-if="isStringArray(field.schema)"
        :value="stringArrayFieldValue(field.name)"
        :options="arrayOptions(field.name, field.schema)"
        multiple
        tag
        filterable
        clearable
        size="small"
        :status="fieldInvalid(field) ? 'error' : undefined"
        :placeholder="fieldPlaceholder(field)"
        @update:value="setFieldValue(field.name, $event)"
      />
      <div v-else-if="field.schema.type === 'boolean'" class="boolean-field">
        <n-switch
          :value="Boolean(fieldValue(field.name))"
          size="small"
          @update:value="setFieldValue(field.name, $event)"
        />
        <span>{{ fieldValue(field.name) ? '开启' : '关闭' }}</span>
      </div>
      <n-input
        v-else
        :value="stringFieldValue(field.name)"
        :type="secretFields.includes(field.name) ? 'password' : 'text'"
        :show-password-on="secretFields.includes(field.name) ? 'click' : undefined"
        :minlength="field.schema.minLength"
        :maxlength="field.schema.maxLength"
        size="small"
        :status="fieldInvalid(field) ? 'error' : undefined"
        :placeholder="fieldPlaceholder(field)"
        @update:value="setFieldValue(field.name, $event)"
      />
      <span v-if="fieldInvalid(field)" class="resource-field-error">
        {{ t('validation.required') }}
      </span>
      <span v-if="field.schema.description" class="resource-field-description">
        {{ field.schema.description }}
      </span>
    </label>
  </div>
  <n-input
    v-else
    :value="rawValue"
    type="textarea"
    :autosize="{ minRows: 3, maxRows: 8 }"
    size="small"
    :status="rawValueInvalid ? 'error' : undefined"
    placeholder="填写符合 Resource Schema 的 JSON 值"
    @update:value="emit('update:modelValue', $event)"
  />
  <span v-if="rawValueInvalid" class="resource-field-error">
    {{ t('validation.required') }}
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NInput, NInputNumber, NSelect, NSwitch } from 'naive-ui'
import { useI18n } from '@/composables/useI18n'
import {
  resourceFieldComplete,
  resourceSchemaFields,
  type ResourceJsonSchema,
  type ResourceSchemaField,
} from './resourceSchema'

const props = withDefaults(defineProps<{
  modelValue: unknown
  schema: Record<string, unknown>
  secretFields?: string[]
  showValidation?: boolean
}>(), {
  secretFields: () => [],
  showValidation: false,
})

const emit = defineEmits<{
  'update:modelValue': [value: unknown]
}>()

const fields = computed(() => resourceSchemaFields(props.schema))
const rawValue = computed(() => typeof props.modelValue === 'string' ? props.modelValue : '')
const rawValueInvalid = computed(() => props.showValidation && !fields.value && rawValue.value.trim().length === 0)
const { t } = useI18n()

function fieldValue(name: string): unknown {
  return draftObject()[name] ?? null
}

function enumFieldValue(name: string): string | number | null {
  const value = fieldValue(name)
  return typeof value === 'string' || typeof value === 'number' ? value : null
}

function stringFieldValue(name: string): string {
  const value = fieldValue(name)
  return value == null ? '' : String(value)
}

function numberFieldValue(name: string): number | null {
  const value = fieldValue(name)
  return typeof value === 'number' ? value : null
}

function stringArrayFieldValue(name: string): string[] {
  const value = fieldValue(name)
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
}

function setFieldValue(name: string, value: unknown): void {
  emit('update:modelValue', { ...draftObject(), [name]: value })
}

function draftObject(): Record<string, unknown> {
  return props.modelValue && typeof props.modelValue === 'object' && !Array.isArray(props.modelValue)
    ? props.modelValue as Record<string, unknown>
    : {}
}

function enumOptions(values: unknown[]): Array<{ label: string; value: string | number }> {
  return values
    .filter((value): value is string | number => typeof value === 'string' || typeof value === 'number')
    .map(value => ({ label: String(value), value }))
}

function arrayOptions(name: string, schema: ResourceJsonSchema): Array<{ label: string; value: string }> {
  const declared = Array.isArray(schema.items?.enum)
    ? schema.items.enum.filter((value): value is string => typeof value === 'string')
    : []
  return [...new Set([...declared, ...stringArrayFieldValue(name)])]
    .map(value => ({ label: value, value }))
}

function isStringArray(schema: ResourceJsonSchema): boolean {
  return schema.type === 'array' && schema.items?.type === 'string'
}

function schemaRecord(schema: ResourceJsonSchema): Record<string, unknown> {
  return schema as unknown as Record<string, unknown>
}

function childSecretFields(name: string): string[] {
  const dottedPrefix = `${name}.`
  const pointerPrefix = `/${name}/`
  return props.secretFields.flatMap((path) => {
    if (path.startsWith(dottedPrefix)) return [path.slice(dottedPrefix.length)]
    if (path.startsWith(pointerPrefix)) return [path.slice(pointerPrefix.length).split('/').join('.')]
    return []
  })
}

function fieldPlaceholder(field: ResourceSchemaField): string {
  if (isStringArray(field.schema)) return `输入${field.schema.title || field.name}后按回车添加`
  return field.required ? `填写 ${field.schema.title || field.name}` : `可选：${field.schema.title || field.name}`
}

function fieldInvalid(field: ResourceSchemaField): boolean {
  return props.showValidation
    && field.required
    && !resourceFieldComplete(field.schema, fieldValue(field.name))
}
</script>

<style scoped>
.resource-schema-form {
  display: grid;
  gap: var(--app-space-sm);
}

.resource-field {
  display: grid;
  gap: var(--app-space-xs);
}

.resource-field-label {
  color: var(--app-text-secondary);
  font-size: var(--app-font-sm);
  font-weight: 500;
}

.required-mark {
  color: var(--n-color-error, #d03050);
}

.resource-field-description,
.boolean-field {
  color: var(--app-text-muted);
  font-size: var(--app-font-xs);
}

.resource-field-error {
  color: var(--n-color-error, #d03050);
  font-size: var(--app-font-xs);
}

.boolean-field {
  display: flex;
  align-items: center;
  gap: var(--app-space-sm);
}

.nested-resource-form {
  padding-left: var(--app-space-sm);
  border-left: 2px solid var(--app-divider);
}
</style>
