<template>
  <div class="mcp-test-details">
    <div class="result-message">{{ result.message || t('extensions.noTestResult') }}</div>

    <div v-if="tools.length" class="result-tools">
      <n-tag
        v-for="tool in tools"
        :key="tool.name"
        size="small"
        :bordered="false"
      >
        {{ tool.name }}
      </n-tag>
    </div>

    <details v-if="details.length" :open="failed">
      <summary>{{ t('extensions.internalErrors') }}</summary>
      <ul class="detail-list">
        <li v-for="(detail, index) in details" :key="`${index}:${detail}`">{{ detail }}</li>
      </ul>
    </details>

    <details v-if="stderr.length" :open="failed">
      <summary>{{ t('extensions.processOutput') }}</summary>
      <pre class="process-output">{{ stderr.join('\n') }}</pre>
    </details>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NTag } from 'naive-ui'
import { useI18n } from '@/composables/useI18n'

const props = defineProps<{
  result: Record<string, any>
}>()

const { t } = useI18n()
const failed = computed(() => props.result.status !== 'ok')
const details = computed<string[]>(() => stringArray(props.result.details))
const stderr = computed<string[]>(() => stringArray(props.result.stderr))
const tools = computed<Array<{ name: string }>>(() => (
  Array.isArray(props.result.tools)
    ? props.result.tools
        .filter((tool: unknown): tool is Record<string, unknown> => Boolean(tool) && typeof tool === 'object')
        .map(tool => ({ name: String(tool.name || 'tool') }))
    : []
))

function stringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.map(item => String(item || '').trim()).filter(Boolean)
    : []
}
</script>

<style scoped>
.mcp-test-details {
  display: grid;
  gap: var(--app-space-sm);
  min-width: 0;
}

.result-message {
  color: var(--app-text-primary);
  overflow-wrap: anywhere;
}

.result-tools {
  display: flex;
  flex-wrap: wrap;
  gap: var(--app-space-xs);
}

details {
  color: var(--app-text-secondary);
}

summary {
  cursor: pointer;
  font-size: var(--app-font-sm);
  font-weight: 500;
}

.detail-list {
  margin: var(--app-space-xs) 0 0;
  padding-left: var(--app-space-xl);
}

.process-output {
  max-height: 240px;
  margin: var(--app-space-xs) 0 0;
  padding: var(--app-space-sm);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface-muted);
  color: var(--app-text-secondary);
  font-family: var(--app-font-mono);
  font-size: var(--app-font-xs);
  line-height: 1.5;
  overflow: auto;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
</style>
