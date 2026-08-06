<template>
  <section class="resource-request-panel">
    <div class="resource-request-header">
      <div>
        <div class="resource-request-title">需要运行时资源配置</div>
        <div class="resource-request-hint">值会加密保存，只在工具执行时由 Gateway 注入，不会写入 AgentPackage 或模型上下文。</div>
      </div>
    </div>

    <div v-for="request in requests" :key="request.resource_id" class="resource-request-card">
      <div class="resource-request-copy">
        <strong>{{ request.resource_id }}</strong>
        <span>{{ request.description || '此能力需要运行时资源后才能使用。' }}</span>
      </div>
      <ResourceSchemaForm
        :model-value="drafts[request.resource_id]"
        :schema="request.value_schema || {}"
        :secret-fields="request.secret_fields || (request.secret ? [''] : [])"
        :show-validation="validationVisible"
        @update:model-value="drafts[request.resource_id] = $event"
      />
      <div v-if="errors[request.resource_id]" class="resource-request-error">
        {{ errors[request.resource_id] }}
      </div>
    </div>

    <div class="resource-request-actions">
      <n-button size="small" quaternary :disabled="saving" @click="$emit('skip')">稍后配置</n-button>
      <n-button type="primary" size="small" :loading="saving" @click="saveAll">
        保存并继续
      </n-button>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { NButton } from 'naive-ui'
import { createAgentApi } from '@/api/createAgent'
import ResourceSchemaForm from '@/components/agent/ResourceSchemaForm.vue'
import {
  createResourceDraft,
  resourceDraftComplete,
  resourceDraftValue,
} from '@/components/agent/resourceSchema'

interface ResourceRequestView {
  resource_id: string
  description?: string
  secret?: boolean
  required?: boolean
  value_schema?: Record<string, unknown>
  secret_fields?: string[]
}

const props = defineProps<{ workspaceId: string; requests: ResourceRequestView[] }>()
const emit = defineEmits<{ configured: [resourceIds: string[]]; skip: [] }>()
const drafts = ref<Record<string, unknown>>({})
const errors = ref<Record<string, string>>({})
const saving = ref(false)
const validationVisible = ref(false)

const allComplete = computed(() => props.requests.length > 0 && props.requests.every((request) => (
  resourceDraftComplete(request.value_schema || {}, drafts.value[request.resource_id])
)))

watch(
  () => props.requests,
  (requests) => {
    drafts.value = Object.fromEntries(requests.map((request) => [
      request.resource_id,
      createResourceDraft(request.value_schema || {}),
    ]))
    errors.value = {}
    validationVisible.value = false
  },
  { immediate: true, deep: true },
)

async function saveAll() {
  if (saving.value) return
  validationVisible.value = true
  if (!allComplete.value) return
  saving.value = true
  errors.value = {}
  const saved: string[] = []
  try {
    for (const request of props.requests) {
      try {
        const value = resourceDraftValue(request.value_schema || {}, drafts.value[request.resource_id])
        await createAgentApi.putResource(props.workspaceId, request.resource_id, value)
        saved.push(request.resource_id)
      } catch (error) {
        errors.value = {
          ...errors.value,
          [request.resource_id]: error instanceof Error ? error.message : String(error),
        }
        return
      }
    }
    emit('configured', saved)
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.resource-request-panel {
  border-top: 1px solid var(--app-border);
  padding: var(--app-space-md);
  display: grid;
  gap: var(--app-space-sm);
  background: var(--app-surface);
}

.resource-request-header,
.resource-request-card,
.resource-request-actions {
  width: min(100%, 920px);
  margin: 0 auto;
}

.resource-request-title { font-weight: 600; }
.resource-request-hint,
.resource-request-copy span {
  color: var(--app-text-muted);
  font-size: 12px;
  line-height: 1.5;
}

.resource-request-card {
  display: grid;
  gap: var(--app-space-sm);
  padding: var(--app-space-md);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
}

.resource-request-copy { display: grid; gap: 2px; font-size: 13px; }
.resource-request-actions { display: flex; justify-content: flex-end; gap: var(--app-space-xs); }
.resource-request-error { color: var(--app-error); font-size: 12px; }
</style>
