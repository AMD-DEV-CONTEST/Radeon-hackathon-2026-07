<template>
  <section class="tool-approval-panel">
    <div class="approval-header">
      <div class="approval-title">
        <n-icon size="18">
          <ShieldCheckmark />
        </n-icon>
        <span>{{ t('tool.pendingApproval') }}</span>
      </div>
      <n-tag size="small" :bordered="false">
        {{ t('common.itemCount', { count: requests.length }) }}
      </n-tag>
    </div>

    <div class="approval-list">
      <div
        v-for="(request, index) in requests"
        :key="requestKey(request, index)"
        class="approval-item"
      >
        <div class="tool-line">
          <n-text strong>{{ toolName(request) }}</n-text>
          <n-tag size="small" :type="riskTagType(request)">
            {{ riskLabel(request) }}
          </n-tag>
        </div>

        <p v-if="toolSummary(request)" class="tool-summary">
          {{ toolSummary(request) }}
        </p>

        <div v-if="riskReasons(request).length > 0" class="risk-reasons">
          <span
            v-for="reason in riskReasons(request)"
            :key="reason"
            class="risk-reason"
          >
            {{ reason }}
          </span>
        </div>

        <n-collapse v-if="hasArguments(request)" class="arguments-collapse" arrow-placement="right">
          <n-collapse-item :title="t('tool.arguments')" name="arguments">
            <pre class="arguments-block">{{ formatArguments(request) }}</pre>
          </n-collapse-item>
        </n-collapse>
      </div>
    </div>

    <div class="revision-row">
      <n-input
        v-model:value="revisionGuidance"
        type="textarea"
        size="small"
        :placeholder="t('tool.revisionPlaceholder')"
        :autosize="{ minRows: 2, maxRows: 4 }"
      />
    </div>

    <div class="approval-actions">
      <n-space justify="end" :wrap="true">
        <n-button size="small" @click="handleDeny">
          <template #icon>
            <n-icon><CloseCircle /></n-icon>
          </template>
          {{ t('tool.deny') }}
        </n-button>
        <n-button size="small" :disabled="!revisionGuidance.trim()" @click="handleRevise">
          <template #icon>
            <n-icon><CreateOutline /></n-icon>
          </template>
          {{ t('tool.revise') }}
        </n-button>
        <n-button size="small" @click="handleTrust">
          <template #icon>
            <n-icon><Shield /></n-icon>
          </template>
          {{ t('tool.trust') }}
        </n-button>
        <n-button size="small" type="primary" @click="handleApprove">
          <template #icon>
            <n-icon><CheckmarkCircle /></n-icon>
          </template>
          {{ t('tool.approve') }}
        </n-button>
      </n-space>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  NButton,
  NCollapse,
  NCollapseItem,
  NIcon,
  NInput,
  NSpace,
  NTag,
  NText,
} from 'naive-ui'
import {
  CheckmarkCircle,
  CloseCircle,
  CreateOutline,
  Shield,
  ShieldCheckmark,
} from '@/components/icons'
import { useCommand } from '@/composables/useCommand'
import { useI18n } from '@/composables/useI18n'
import { useRuntimeStore } from '@/stores/runtime'

type ApprovalRequest = Record<string, any>

const props = defineProps<{
  requests?: ApprovalRequest[]
}>()
const emit = defineEmits<{
  resolve: [payload: Record<string, unknown>]
}>()
const runtimeStore = useRuntimeStore()
const commands = useCommand()
const { t } = useI18n()
const revisionGuidance = ref('')

const requests = computed<ApprovalRequest[]>(() => props.requests || runtimeStore.currentApprovalRequests)

function requestKey(request: ApprovalRequest, index: number): string {
  return String(request.tool_call_id || request.tool_name || request.name || index)
}

function toolName(request: ApprovalRequest): string {
  return String(request.tool_name || request.tool_id || request.name || t('tool.call'))
}

function toolSummary(request: ApprovalRequest): string {
  return String(request.summary || request.message || '')
}

function riskLevel(request: ApprovalRequest): string {
  return String(request.risk_level || request.risk || 'standard').toLowerCase()
}

function riskLabel(request: ApprovalRequest): string {
  const level = riskLevel(request)
  const labels: Record<string, string> = {
    low: t('tool.risk.low'),
    medium: t('tool.risk.medium'),
    high: t('tool.risk.high'),
    critical: t('tool.risk.high'),
    standard: t('tool.risk.standard'),
  }
  return labels[level] || level
}

function riskTagType(request: ApprovalRequest): 'default' | 'success' | 'warning' | 'error' | 'info' {
  const level = riskLevel(request)
  if (level === 'high' || level === 'critical') return 'error'
  if (level === 'medium') return 'warning'
  if (level === 'low') return 'default'
  return 'info'
}

function riskReasons(request: ApprovalRequest): string[] {
  const reasons = request.risk_reasons
  if (!Array.isArray(reasons)) return []
  return reasons.map((reason) => String(reason)).filter(Boolean)
}

function requestArguments(request: ApprovalRequest): Record<string, any> {
  const args = request.args || request.arguments || {}
  return args && typeof args === 'object' && !Array.isArray(args) ? args : {}
}

function hasArguments(request: ApprovalRequest): boolean {
  return Object.keys(requestArguments(request)).length > 0
}

function formatArguments(request: ApprovalRequest): string {
  return JSON.stringify(requestArguments(request), null, 2)
}

function handleApprove() {
  if (props.requests) {
    emit('resolve', { action: 'approve', approved: true })
    return
  }
  commands.approveToolCall()
}

function handleDeny() {
  if (props.requests) {
    emit('resolve', { action: 'deny', approved: false })
    return
  }
  commands.denyToolCall()
}

function handleTrust() {
  if (props.requests) {
    emit('resolve', { action: 'trust_tool', approved: true, trust_scope: 'tool' })
    return
  }
  commands.trustTool()
}

function handleRevise() {
  const guidance = revisionGuidance.value.trim()
  if (!guidance) return
  if (props.requests) {
    emit('resolve', { action: 'revise', revision_guidance: guidance })
    revisionGuidance.value = ''
    return
  }
  commands.reviseWithGuidance(guidance)
  revisionGuidance.value = ''
}
</script>

<style scoped>
.tool-approval-panel {
  padding: var(--app-space-lg);
  border: 1px solid var(--app-text);
  border-radius: var(--app-radius-lg);
  background: var(--app-surface);
  color: var(--app-text);
  box-shadow: var(--app-shadow-md);
  animation: app-fade-in-up 0.28s cubic-bezier(0.16, 1, 0.3, 1) both;
  position: relative;
}

.tool-approval-panel::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  border-radius: var(--app-radius-lg) 0 0 var(--app-radius-lg);
  background: var(--app-warning);
  animation: app-pulse-soft 1.6s ease-in-out infinite;
}

.approval-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.approval-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
}

.approval-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 12px;
}

.approval-item {
  padding-top: 12px;
  border-top: 1px solid var(--app-divider);
}

.tool-line {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.tool-summary {
  margin: 8px 0 0;
  color: var(--app-text-secondary);
  font-size: 13px;
  line-height: 1.5;
}

.risk-reasons {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.risk-reason {
  max-width: 100%;
  padding: 2px 8px;
  border: 1px solid var(--app-border);
  border-radius: 999px;
  color: var(--app-text-secondary);
  font-size: 12px;
  line-height: 1.6;
}

.arguments-collapse {
  margin-top: 8px;
}

.arguments-block {
  margin: 0;
  padding: 10px 12px;
  overflow: auto;
  max-height: 180px;
  border: 1px solid var(--app-code-border);
  border-radius: var(--app-radius-md);
  background: var(--app-code-background);
  color: var(--app-text);
  font-family: 'SF Mono', Monaco, 'Cascadia Code', 'Roboto Mono', monospace;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}

.revision-row {
  margin-top: 12px;
}

.approval-actions {
  margin-top: 12px;
}
</style>
