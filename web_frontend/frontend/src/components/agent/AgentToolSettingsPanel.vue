<template>
  <section class="tool-settings-panel">
    <div class="section-heading">
      <div>
        <div class="section-title">{{ t('agentTools.title') }}</div>
        <div class="section-hint">{{ t('agentTools.description') }}</div>
      </div>
      <n-tag size="small" :bordered="false">{{ settings?.tools.length || 0 }}</n-tag>
    </div>

    <n-spin :show="loading">
      <div v-if="settings" class="tool-settings-content">
        <div class="approval-overview">
          <div class="approval-copy">
            <strong>{{ t('agentTools.globalApproval') }}</strong>
            <span>{{ policyExplanation }}</span>
          </div>
          <n-radio-group
            :value="settings.policy.mode"
            size="small"
            :disabled="policySaving"
            @update:value="savePolicyMode"
          >
            <n-radio-button value="allow_below_high">{{ t('agentTools.askHighRisk') }}</n-radio-button>
            <n-radio-button value="strict">{{ t('agentTools.askEveryTime') }}</n-radio-button>
            <n-radio-button value="allow_all">{{ t('agentTools.allowAll') }}</n-radio-button>
          </n-radio-group>
        </div>

        <n-alert v-if="error" type="error" :show-icon="false">{{ error }}</n-alert>
        <n-input
          v-model:value="query"
          clearable
          size="small"
          :placeholder="t('agentTools.search')"
        />

        <n-empty v-if="filteredTools.length === 0" :description="t('permissions.noTools')" />
        <n-collapse v-else accordion class="tool-list">
          <n-collapse-item v-for="tool in filteredTools" :key="tool.tool_id" :name="tool.tool_id">
            <template #header>
              <div class="tool-summary">
                <div>
                  <strong>{{ tool.name }}</strong>
                  <code>{{ tool.tool_id }}</code>
                </div>
                <div class="summary-tags">
                  <n-tag size="small" :bordered="false">{{ sourceLabel(tool.source) }}</n-tag>
                  <n-tag size="small" :bordered="false">
                    {{ tool.concurrent ? t('agentTools.concurrent') : t('agentTools.serial') }}
                  </n-tag>
                  <n-tag size="small" :type="approvalTagType(tool)">{{ approvalLabel(toolApproval(tool)) }}</n-tag>
                </div>
              </div>
            </template>

            <div class="tool-editor">
              <div class="field-block">
                <div class="field-label">
                  <strong>{{ t('agentTools.toolDescription') }}</strong>
                  <span>{{ t('agentTools.toolDescriptionHint') }}</span>
                </div>
                <n-input
                  v-model:value="drafts[tool.tool_id].description"
                  type="textarea"
                  :autosize="{ minRows: 3, maxRows: 8 }"
                  :placeholder="tool.base_description || t('permissions.noDescription')"
                />
              </div>

              <div class="field-grid">
                <div class="field-block">
                  <div class="field-label">
                    <strong>{{ t('agentTools.approval') }}</strong>
                    <span>{{ t('agentTools.approvalHint') }}</span>
                  </div>
                  <n-select
                    v-model:value="drafts[tool.tool_id].approval"
                    :options="approvalOptions"
                  />
                </div>
                <div class="field-block">
                  <div class="field-label">
                    <strong>{{ t('agentTools.compressionThreshold') }}</strong>
                    <span>{{ t('agentTools.compressionThresholdHint') }}</span>
                  </div>
                  <n-input-number
                    v-model:value="drafts[tool.tool_id].maxModelChars"
                    :min="1000"
                    :max="1000000"
                    :step="1000"
                    :show-button="false"
                  >
                    <template #suffix>{{ t('agentTools.characters') }}</template>
                  </n-input-number>
                </div>
                <div class="field-block">
                  <div class="field-label">
                    <strong>{{ t('agentTools.concurrentExecution') }}</strong>
                    <span>{{ t('agentTools.concurrentExecutionHint') }}</span>
                  </div>
                  <div class="concurrency-control">
                    <n-switch v-model:value="drafts[tool.tool_id].concurrent" />
                    <span>
                      {{ drafts[tool.tool_id].concurrent
                        ? t('agentTools.concurrentEnabled')
                        : t('agentTools.concurrentDisabled') }}
                    </span>
                  </div>
                </div>
              </div>

              <div v-if="toolErrors[tool.tool_id]" class="tool-error">{{ toolErrors[tool.tool_id] }}</div>
              <div class="tool-actions">
                <n-button
                  size="small"
                  quaternary
                  :disabled="toolSavingId === tool.tool_id"
                  @click="resetTool(tool)"
                >
                  {{ t('agentTools.restoreDefaults') }}
                </n-button>
                <n-button
                  size="small"
                  type="primary"
                  :loading="toolSavingId === tool.tool_id"
                  :disabled="!toolDirty(tool)"
                  @click="saveTool(tool)"
                >
                  {{ t('common.save') }}
                </n-button>
              </div>
            </div>
          </n-collapse-item>
        </n-collapse>
      </div>
    </n-spin>
  </section>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import {
  NAlert,
  NButton,
  NCollapse,
  NCollapseItem,
  NEmpty,
  NInput,
  NInputNumber,
  NRadioButton,
  NRadioGroup,
  NSelect,
  NSpin,
  NSwitch,
  NTag,
} from 'naive-ui'
import {
  agentPackagesApi,
  type AgentToolApproval,
  type AgentToolPolicyMode,
  type AgentToolSettingView,
  type AgentToolSettingsView,
} from '@/api/agentPackages'
import { useI18n } from '@/composables/useI18n'

const props = defineProps<{ packageId: string }>()
const { t } = useI18n()
const settings = ref<AgentToolSettingsView | null>(null)
const loading = ref(false)
const policySaving = ref(false)
const toolSavingId = ref('')
const error = ref('')
const toolErrors = ref<Record<string, string>>({})
const query = ref('')
interface ToolDraft {
  description: string
  approval: AgentToolApproval
  maxModelChars: number | null
  concurrent: boolean
}

const drafts = reactive<Record<string, ToolDraft>>({})

const approvalOptions = computed(() => [
  { label: t('permissions.approval.inherit'), value: 'inherit' },
  { label: t('permissions.approval.allow'), value: 'allow' },
  { label: t('permissions.approval.ask'), value: 'ask' },
  { label: t('permissions.approval.deny'), value: 'deny' },
])
const filteredTools = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  if (!keyword) return settings.value?.tools || []
  return (settings.value?.tools || []).filter(tool => (
    `${tool.name} ${tool.tool_id} ${tool.description}`.toLowerCase().includes(keyword)
  ))
})
const policyExplanation = computed(() => ({
  allow_all: t('agentTools.allowAllHint'),
  strict: t('agentTools.askEveryTimeHint'),
  allow_below_high: t('agentTools.askHighRiskHint'),
  custom: t('agentTools.customPolicyHint'),
}[settings.value?.policy.mode || 'allow_below_high']))

watch(() => props.packageId, loadSettings, { immediate: true })

async function loadSettings(): Promise<void> {
  if (!props.packageId) return
  loading.value = true
  error.value = ''
  try {
    applySettings((await agentPackagesApi.toolSettings(props.packageId)).tool_settings)
  } catch (reason) {
    error.value = errorMessage(reason)
  } finally {
    loading.value = false
  }
}

function applySettings(next: AgentToolSettingsView): void {
  settings.value = next
  for (const key of Object.keys(drafts)) delete drafts[key]
  for (const tool of next.tools) {
    drafts[tool.tool_id] = {
      description: tool.description,
      approval: toolApproval(tool),
      maxModelChars: tool.max_model_chars,
      concurrent: tool.concurrent,
    }
  }
  toolErrors.value = {}
}

async function savePolicyMode(value: string): Promise<void> {
  if (!settings.value) return
  policySaving.value = true
  error.value = ''
  try {
    const response = await agentPackagesApi.updateToolPolicy(props.packageId, value as AgentToolPolicyMode)
    applySettings(response.tool_settings)
  } catch (reason) {
    error.value = errorMessage(reason)
  } finally {
    policySaving.value = false
  }
}

async function saveTool(tool: AgentToolSettingView): Promise<void> {
  const draft = drafts[tool.tool_id]
  if (!draft) return
  const description = draft.description.trim()
  if (!description) {
    toolErrors.value = { ...toolErrors.value, [tool.tool_id]: t('agentTools.descriptionRequired') }
    return
  }
  if (draft.maxModelChars === null) {
    toolErrors.value = { ...toolErrors.value, [tool.tool_id]: t('agentTools.thresholdRequired') }
    return
  }
  const maxModelChars = draft.maxModelChars
  toolSavingId.value = tool.tool_id
  toolErrors.value = { ...toolErrors.value, [tool.tool_id]: '' }
  try {
    const response = await agentPackagesApi.updateToolSettings(props.packageId, tool.tool_id, {
      description,
      max_model_chars: maxModelChars,
      approval: draft.approval,
      concurrent: draft.concurrent,
    })
    const persisted = response.tool_settings.tools.find(item => item.tool_id === tool.tool_id)
    const persistedApproval = response.tool_settings.policy.tool_overrides?.[tool.tool_id]?.approval || 'inherit'
    if (
      !persisted
      || persisted.description !== description
      || persisted.max_model_chars !== maxModelChars
      || persisted.concurrent !== draft.concurrent
      || persistedApproval !== draft.approval
    ) {
      throw new Error(t('agentTools.persistenceMismatch'))
    }
    applySettings(response.tool_settings)
  } catch (reason) {
    toolErrors.value = { ...toolErrors.value, [tool.tool_id]: errorMessage(reason) }
  } finally {
    toolSavingId.value = ''
  }
}

async function resetTool(tool: AgentToolSettingView): Promise<void> {
  toolSavingId.value = tool.tool_id
  toolErrors.value = { ...toolErrors.value, [tool.tool_id]: '' }
  try {
    applySettings((await agentPackagesApi.resetToolSettings(props.packageId, tool.tool_id)).tool_settings)
  } catch (reason) {
    toolErrors.value = { ...toolErrors.value, [tool.tool_id]: errorMessage(reason) }
  } finally {
    toolSavingId.value = ''
  }
}

function toolApproval(tool: AgentToolSettingView): AgentToolApproval {
  return settings.value?.policy.tool_overrides?.[tool.tool_id]?.approval || 'inherit'
}

function toolDirty(tool: AgentToolSettingView): boolean {
  const draft = drafts[tool.tool_id]
  return Boolean(draft) && (
    draft.description.trim() !== tool.description
    || draft.maxModelChars !== tool.max_model_chars
    || draft.concurrent !== tool.concurrent
    || draft.approval !== toolApproval(tool)
  )
}

function approvalLabel(approval: AgentToolApproval): string {
  return approvalOptions.value.find(option => option.value === approval)?.label || approval
}

function approvalTagType(tool: AgentToolSettingView): 'default' | 'success' | 'warning' | 'error' {
  const approval = toolApproval(tool)
  if (approval === 'allow') return 'success'
  if (approval === 'ask') return 'warning'
  if (approval === 'deny') return 'error'
  return 'default'
}

function sourceLabel(source: string): string {
  const labels: Record<string, string> = {
    system: t('permissions.source.system'),
    package: t('permissions.source.package'),
    extension: t('permissions.source.extension'),
    model: t('permissions.source.model'),
    mcp: t('permissions.source.mcp'),
  }
  return labels[source] || source
}

function errorMessage(reason: unknown): string {
  return reason instanceof Error ? reason.message : String(reason)
}
</script>

<style scoped>
.tool-settings-panel { display: flex; flex-direction: column; gap: 14px; }
.section-heading, .tool-summary, .tool-actions { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.section-title { font-size: 15px; font-weight: 650; color: var(--app-text-primary); }
.section-hint, .approval-copy span, .field-label span { color: var(--app-text-secondary); font-size: 12px; line-height: 1.55; }
.tool-settings-content { display: flex; flex-direction: column; gap: 12px; }
.approval-overview { display: flex; flex-direction: column; gap: 10px; padding: 12px; border: 1px solid var(--app-border); border-radius: 12px; background: var(--app-surface); }
.approval-copy { display: flex; flex-direction: column; gap: 3px; }
.tool-list { border-top: 1px solid var(--app-border); }
.tool-summary { width: 100%; padding-right: 8px; }
.tool-summary > div:first-child { display: flex; min-width: 0; flex-direction: column; gap: 2px; }
.tool-summary code { color: var(--app-text-secondary); font-size: 11px; }
.summary-tags { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 6px; }
.tool-editor { display: flex; flex-direction: column; gap: 14px; padding: 4px 0 12px; }
.field-block, .field-label { display: flex; flex-direction: column; gap: 6px; }
.field-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 12px; }
.concurrency-control { display: flex; min-height: 34px; align-items: center; gap: 10px; color: var(--app-text-secondary); font-size: 12px; }
.tool-error { color: var(--app-danger); font-size: 12px; }
@media (max-width: 560px) { .field-grid { grid-template-columns: 1fr; } }
</style>
