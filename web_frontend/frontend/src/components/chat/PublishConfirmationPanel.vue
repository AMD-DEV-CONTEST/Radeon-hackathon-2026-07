<template>
  <section class="publish-confirmation-panel">
    <div class="publish-header">
      <div class="publish-title">
        <n-icon size="18">
          <RocketOutline />
        </n-icon>
        <span>{{ t('publish.title') }}</span>
      </div>
      <n-tag size="small" type="success" :bordered="false">
        {{ validationLabel }}
      </n-tag>
    </div>

    <p class="publish-message">{{ t('publish.defaultMessage') }}</p>

    <dl class="publish-details">
      <div class="publish-detail-row">
        <dt>{{ t('publish.workspace') }}</dt>
        <dd :title="workspacePath">{{ workspaceDisplay }}</dd>
      </div>
      <div class="publish-detail-row">
        <dt>{{ t('publish.validation') }}</dt>
        <dd>{{ validationLabel }}</dd>
      </div>
      <div v-if="validationSummary" class="publish-detail-row">
        <dt>{{ t('publish.summary') }}</dt>
        <dd>{{ validationSummary }}</dd>
      </div>
    </dl>

    <div v-if="pendingResources.length" class="publish-resource-notice">
      <strong>发布后待配置 Resource</strong>
      <span>{{ pendingResources.map(item => item.resource_id).join('、') }}</span>
      <small>这些配置不阻断发布；对应工具在包详情中完成配置前不可执行。</small>
    </div>

    <div v-if="revisionEnabled" class="revision-row">
      <n-input
        v-model:value="revisionGuidance"
        type="textarea"
        size="small"
        :placeholder="t('publish.revisionPlaceholder')"
        :autosize="{ minRows: 2, maxRows: 4 }"
      />
    </div>

    <div class="publish-actions">
      <n-space justify="end" :wrap="true">
        <n-button
          v-if="revisionEnabled"
          size="small"
          :disabled="!revisionGuidance.trim()"
          @click="handleContinueRevision"
        >
          <template #icon>
            <n-icon><CreateOutline /></n-icon>
          </template>
          {{ t('publish.continueRevision') }}
        </n-button>
        <n-button
          size="small"
          type="primary"
          :loading="publishSubmitting"
          @click="handleConfirmPublish"
        >
          <template #icon>
            <n-icon><CheckmarkCircle /></n-icon>
          </template>
          {{ t('publish.confirm') }}
        </n-button>
      </n-space>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { NButton, NIcon, NInput, NSpace, NTag } from 'naive-ui'
import { createAgentApi } from '@/api/createAgent'
import { CheckmarkCircle, CreateOutline, RocketOutline } from '@/components/icons'
import { useCommand } from '@/composables/useCommand'
import { useI18n } from '@/composables/useI18n'
import { useRuntimeStore } from '@/stores/runtime'
import { useUiStore } from '@/stores/ui'

const runtimeStore = useRuntimeStore()
const commands = useCommand()
const uiStore = useUiStore()
const { t } = useI18n()
const revisionGuidance = ref('')
const publishSubmitting = ref(false)

const props = withDefaults(defineProps<{
  publishPayload?: Record<string, any> | null
  revisionEnabled?: boolean
}>(), {
  publishPayload: null,
  revisionEnabled: true,
})
const emit = defineEmits<{
  published: [result: Record<string, any>]
}>()

const payload = computed(() => props.publishPayload || runtimeStore.publishConfirmationPayload || {})
const workspacePath = computed(() => String(
  payload.value.source_workspace || payload.value.workspace_path || '',
).trim())
const workspaceDisplay = computed(() => (
  String(payload.value.workspace_id || '').trim()
  || workspacePath.value
  || t('publish.workspaceUnknown')
))
const pendingResources = computed<Array<{ resource_id: string }>>(() => {
  const values = payload.value.runtime_configuration?.pending_resources
  if (!Array.isArray(values)) return []
  return values.filter((item): item is { resource_id: string } => Boolean(item && typeof item.resource_id === 'string'))
})
const validationLabel = computed(() => {
  const validation = payload.value.validation
  if (!validation || typeof validation !== 'object') return t('publish.ready')
  const scope = String(validation.validation_scope || '').trim()
  const status = String(validation.status || '').trim()
  return [scope, status].filter(Boolean).join(' / ') || t('publish.ready')
})
const validationSummary = computed(() => {
  const validation = payload.value.validation
  if (!validation || typeof validation !== 'object') return ''
  return String(validation.summary || '').trim()
})

async function handleConfirmPublish() {
  if (publishSubmitting.value) return
  const workspaceId = String(payload.value.workspace_id || '').trim()
  if (!workspaceId) {
    uiStore.addNotification({
      type: 'error',
      title: t('publish.failedTitle'),
      message: t('publish.missingSession'),
      duration: 3500,
    })
    return
  }
  publishSubmitting.value = true
  try {
    const response = await createAgentApi.publish(workspaceId)
    runtimeStore.clearCreateAgentPublishReady()
    commands.listAgentPackages()
    emit('published', response.published)
    uiStore.addNotification({
      type: 'success',
      title: t('publish.successTitle'),
      message: t('publish.successMessage'),
      duration: 3000,
    })
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    uiStore.addNotification({
      type: 'error',
      title: t('publish.failedTitle'),
      message,
      duration: 5000,
    })
  } finally {
    publishSubmitting.value = false
  }
}

function handleContinueRevision() {
  const guidance = revisionGuidance.value.trim()
  if (!guidance) return
  runtimeStore.clearCreateAgentPublishReady()
  commands.sendMessage(guidance, 'create_agent')
  revisionGuidance.value = ''
}
</script>

<style scoped>
.publish-confirmation-panel {
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
  padding: var(--app-space-md);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
  background: var(--app-surface);
  color: var(--app-text);
  box-shadow: var(--app-shadow-sm);
  animation: app-fade-in-up 0.28s cubic-bezier(0.16, 1, 0.3, 1) both;
}

.publish-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.publish-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
}

.publish-message {
  margin: 10px 0 0;
  color: var(--app-text-secondary);
  font-size: 13px;
  line-height: 1.5;
}

.publish-details {
  min-width: 0;
  margin: 12px 0 0;
  padding: 10px 12px;
  border-radius: var(--app-radius-md);
  background: var(--app-surface-muted);
}

.publish-detail-row {
  display: grid;
  grid-template-columns: minmax(64px, auto) minmax(0, 1fr);
  gap: 12px;
  align-items: baseline;
}

.publish-detail-row + .publish-detail-row {
  margin-top: 6px;
}

.publish-detail-row dt {
  color: var(--app-text-muted);
  font-size: 12px;
}

.publish-detail-row dd {
  min-width: 0;
  margin: 0;
  overflow: hidden;
  color: var(--app-text-secondary);
  font-size: 12px;
  line-height: 1.5;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.publish-resource-notice {
  margin-top: 12px;
  display: grid;
  gap: 4px;
  padding: 10px 12px;
  border: 1px solid var(--app-warning);
  border-radius: var(--app-radius-md);
  background: var(--app-surface-muted);
  color: var(--app-text-secondary);
  font-size: 12px;
}

.publish-resource-notice strong { color: var(--app-text); }
.publish-resource-notice small { color: var(--app-text-muted); line-height: 1.5; }

.revision-row {
  margin-top: 14px;
}

.publish-actions {
  margin-top: 12px;
}
</style>
