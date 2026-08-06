<template>
  <n-modal
    v-model:show="show"
    preset="card"
    :title="modalTitle"
    style="width: min(760px, calc(100vw - 32px))"
  >
    <div v-if="!item" class="mode-switch">
      <n-radio-group v-model:value="mode" size="small" class="soft-segmented-control">
        <n-radio-button value="import">{{ t('extensions.mcpImportMode') }}</n-radio-button>
        <n-radio-button value="manual">{{ t('extensions.mcpManualMode') }}</n-radio-button>
      </n-radio-group>
    </div>

    <n-spin :show="Boolean(item && editConfigLoading)">
      <section v-if="mode === 'import'" class="import-panel">
        <n-text depth="3">
          {{ item ? t('extensions.mcpEditJsonHint') : t('extensions.mcpImportHint') }}
        </n-text>
        <n-input
          v-model:value="importText"
          type="textarea"
          :rows="14"
          :placeholder="t('extensions.mcpImportPlaceholder')"
        />
        <n-space v-if="!item" justify="end">
          <n-button @click="parseImport">{{ t('extensions.parseConfig') }}</n-button>
        </n-space>
        <n-alert v-if="importErrors.length" type="error" :title="t('extensions.configInvalid')">
          <div v-for="error in importErrors" :key="error">{{ error }}</div>
        </n-alert>
        <div v-if="!item && importedServers.length" class="preview-list">
          <n-text strong>{{ t('extensions.parsePreview') }}</n-text>
          <div v-for="server in importedServers" :key="server.server_id" class="preview-card">
            <div class="preview-heading">
              <n-text strong>{{ server.display_name }}</n-text>
              <n-tag size="small" :bordered="false">{{ server.transport }}</n-tag>
            </div>
            <n-text depth="3" class="preview-command">{{ serverCommand(server) }}</n-text>
            <div class="preview-meta">
              <span v-if="server.transport === 'stdio'">
                {{ t('extensions.envKeys') }}：{{ recordKeys(server.env) || '—' }}
              </span>
              <span v-else>
                {{ t('extensions.headers') }}：{{ recordKeys(server.headers) || '—' }}
              </span>
            </div>
          </div>
        </div>
      </section>

      <n-form v-else ref="formRef" :model="formData" :rules="rules" label-placement="top">
        <n-grid :cols="2" :x-gap="16">
          <n-form-item-gi :label="t('common.name')" path="display_name">
            <n-input v-model:value="formData.display_name" :placeholder="t('extensions.serverName')" />
          </n-form-item-gi>
          <n-form-item-gi :label="t('extensions.transport')">
            <n-select v-model:value="formData.transport" :options="transportOptions" />
          </n-form-item-gi>
        </n-grid>

        <n-form-item :label="t('common.description')">
          <n-input v-model:value="formData.description" type="textarea" :rows="2" />
        </n-form-item>

        <template v-if="formData.transport === 'stdio'">
          <n-form-item :label="t('extensions.command')" path="command">
            <n-input v-model:value="formData.command" placeholder="npx" />
          </n-form-item>
          <n-form-item :label="t('extensions.arguments')">
            <n-input v-model:value="formData.args" placeholder="-y @modelcontextprotocol/server-filesystem" />
          </n-form-item>
          <n-form-item :label="t('extensions.cwd')">
            <n-input v-model:value="formData.cwd" :placeholder="t('extensions.cwdPlaceholder')" />
          </n-form-item>
          <n-form-item :label="t('extensions.env')">
            <n-input v-model:value="formData.env" type="textarea" :rows="3" placeholder="KEY=value" />
          </n-form-item>
        </template>

        <template v-else>
          <n-form-item label="URL" path="url">
            <n-input v-model:value="formData.url" placeholder="https://example.com/mcp" />
          </n-form-item>
          <n-form-item :label="t('extensions.headers')">
            <n-input v-model:value="formData.headers" type="textarea" :rows="3" placeholder="Authorization=Bearer ..." />
          </n-form-item>
        </template>

        <n-grid :cols="2" :x-gap="16">
          <n-form-item-gi :label="t('extensions.toolCallTimeoutSeconds')">
            <n-input-number v-model:value="formData.timeout_seconds" :min="1" />
          </n-form-item-gi>
          <n-form-item-gi :label="t('permissions.riskLevel')">
            <n-select v-model:value="formData.risk_level_default" :options="riskOptions" />
          </n-form-item-gi>
        </n-grid>
      </n-form>
    </n-spin>

    <n-alert
      v-if="installResult"
      :type="installResultType"
      :title="installResult.message || t('extensions.connectionFailed')"
    >
      <div v-for="test in installResult.tests || []" :key="test.server_id" class="test-row">
        <div class="test-heading">
          <strong>{{ test.server_id }}</strong>
          <n-tag
            size="small"
            :type="test.status === 'ok' ? 'success' : test.status === 'running' ? 'info' : test.status === 'cancelled' ? 'warning' : 'error'"
            :bordered="false"
          >
            {{ testStatusLabel(test.status) }}
          </n-tag>
        </div>
        <McpTestResultDetails :result="test" />
      </div>
    </n-alert>

    <template #footer>
      <n-space justify="space-between">
        <n-text depth="3">{{ t('extensions.mcpInstallNotice') }}</n-text>
        <n-space>
          <n-button
            v-if="busy"
            type="error"
            secondary
            :loading="stopping"
            :disabled="stopping"
            @click="emit('cancel-install')"
          >
            {{ stopping ? t('extensions.mcpInstallStopping') : t('extensions.stopMcpInstall') }}
          </n-button>
          <n-button v-else @click="show = false">{{ t('common.cancel') }}</n-button>
          <n-button
            type="primary"
            :loading="busy"
            :disabled="busy || Boolean(item && editConfigLoading)"
            @click="handleSubmit"
          >
            {{ item ? t('extensions.testAndSave') : t('extensions.testAndAdd') }}
          </n-button>
        </n-space>
      </n-space>
    </template>
  </n-modal>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  NAlert,
  NButton,
  NForm,
  NFormItem,
  NFormItemGi,
  NGrid,
  NInput,
  NInputNumber,
  NModal,
  NRadioButton,
  NRadioGroup,
  NSelect,
  NSpace,
  NSpin,
  NTag,
  NText,
} from 'naive-ui'
import type { FormInst, FormRules } from 'naive-ui'
import type { McpServerConfig } from '@/api/resourceTypes'
import type { ExtensionItemView } from '@/types/protocol'
import { useI18n } from '@/composables/useI18n'
import { requiredTextRule } from '@/utils/formValidation'
import McpTestResultDetails from './McpTestResultDetails.vue'
import {
  mcpConfigArgsText,
  mcpConfigRecordText,
  parseMcpConfigText,
  type McpConfigParserMessages,
} from './mcpConfigParser'

const props = withDefaults(defineProps<{
  show: boolean
  item?: ExtensionItemView | null
  editConfig?: Record<string, unknown> | null
  editConfigLoading?: boolean
  busy?: boolean
  stopping?: boolean
  installResult?: any | null
}>(), {
  busy: false,
  stopping: false,
  installResult: null,
  editConfig: null,
  editConfigLoading: false,
})

const emit = defineEmits<{
  'update:show': [value: boolean]
  submit: [servers: McpServerConfig[]]
  'cancel-install': []
}>()

type McpRiskLevel = NonNullable<McpServerConfig['risk_level_default']>

interface McpFormDraft {
  display_name: string
  description: string
  transport: McpServerConfig['transport']
  command: string
  args: string
  cwd: string
  env: string
  url: string
  headers: string
  timeout_seconds: number
  risk_level_default: McpRiskLevel
}

const show = computed({ get: () => props.show, set: value => emit('update:show', value) })
const { t } = useI18n()
const mcpParserMessages = computed<McpConfigParserMessages>(() => ({
  emptyConfig: t('extensions.mcpImportEmpty'),
  jsonParseFailed: reason => t('extensions.mcpJsonParseFailed', { reason }),
  noRecognizedServers: t('extensions.mcpNoRecognizedServers'),
  serverEntryName: index => t('extensions.mcpServerEntryName', { index }),
  invalidServer: (name, reason) => t('extensions.mcpServerEntryInvalid', { name, reason }),
  duplicateServerIds: ids => t('extensions.mcpDuplicateServerIds', { ids }),
  stdioCommandRequired: t('extensions.mcpStdioCommandRequired'),
  transportUrlRequired: transport => t('extensions.mcpTransportUrlRequired', { transport }),
  unsupportedTransport: transport => t('extensions.mcpUnsupportedTransport', { transport }),
}))
const formRef = ref<FormInst | null>(null)
const mode = ref<'import' | 'manual'>('import')
const importText = ref('')
const importErrors = ref<string[]>([])
const importedServers = ref<McpServerConfig[]>([])
const modalTitle = computed(() => props.item ? t('extensions.mcpEditTitle') : t('extensions.mcpAddTitle'))
const installResultType = computed(() => {
  if (props.installResult?.status === 'ok') return 'success'
  if (props.installResult?.status === 'running') return 'info'
  if (props.installResult?.status === 'cancelled') return 'warning'
  return 'error'
})
const formData = ref<McpFormDraft>(emptyForm())

const transportOptions = computed(() => [
  { label: 'stdio', value: 'stdio' },
  { label: 'Streamable HTTP', value: 'streamable_http' },
  { label: 'SSE', value: 'sse' },
])
const riskOptions = computed(() => [
  { label: t('permissions.risk.low'), value: 'low' },
  { label: t('permissions.risk.medium'), value: 'medium' },
  { label: t('permissions.risk.high'), value: 'high' },
])
const rules = computed<FormRules>(() => ({
  display_name: [requiredTextRule(t('extensions.validateName'))],
  command: [{
    required: formData.value.transport === 'stdio',
    validator: () => formData.value.transport !== 'stdio' || Boolean(formData.value.command.trim()),
    message: t('extensions.validateCommand'),
    trigger: ['input', 'blur'],
  }],
  url: [{
    required: formData.value.transport !== 'stdio',
    validator: () => formData.value.transport === 'stdio' || /^https?:\/\//.test(formData.value.url.trim()),
    message: t('extensions.validateUrl'),
    trigger: ['input', 'blur'],
  }],
}))

function emptyForm(): McpFormDraft {
  return {
    display_name: '', description: '', transport: 'stdio' as McpServerConfig['transport'],
    command: '', args: '', cwd: '', env: '', url: '', headers: '', timeout_seconds: 60,
    risk_level_default: 'medium',
  }
}

function loadForm(item: ExtensionItemView | null | undefined) {
  formData.value = emptyForm()
  if (!item) return
  const payload = item.payload || {}
  formData.value = {
    display_name: String(payload.display_name || item.name || ''),
    description: String(payload.description || ''),
    transport: normalizeTransport(payload.transport),
    command: String(payload.command || ''),
    args: mcpConfigArgsText(payload.args),
    cwd: String(payload.cwd || ''), env: '', url: String(payload.url || ''), headers: '',
    timeout_seconds: Number(payload.timeout_seconds || 60),
    risk_level_default: normalizeRiskLevel(payload.risk_level_default),
  }
}

watch(() => props.show, (visible) => {
  if (!visible) return
  mode.value = 'import'
  importText.value = ''
  importErrors.value = []
  importedServers.value = []
  loadForm(props.item)
  loadEditConfig()
})
watch(() => props.item, item => { if (props.show) loadForm(item) })
watch(() => props.editConfig, () => {
  if (props.show && props.item) loadEditConfig()
})

function loadEditConfig() {
  if (!props.item || !props.editConfig) return
  importText.value = JSON.stringify(props.editConfig, null, 2)
}

function parseImport() {
  const result = parseMcpConfigText(importText.value, mcpParserMessages.value)
  importedServers.value = result.servers
  importErrors.value = result.errors
}

function handleSubmit() {
  if (mode.value === 'import' && props.item) {
    const server = parseEditedServer()
    if (server) emit('submit', [server])
    return
  }
  if (mode.value === 'import') {
    parseImport()
    if (!importedServers.value.length || importErrors.value.length) return
    emit('submit', importedServers.value)
    return
  }
  formRef.value?.validate((errors) => {
    if (errors) return
    emit('submit', [manualServer()])
  })
}

function parseEditedServer(): McpServerConfig | null {
  importErrors.value = []
  let decoded: unknown
  try {
    decoded = JSON.parse(importText.value)
  } catch (error) {
    importErrors.value = [mcpParserMessages.value.jsonParseFailed(
      error instanceof Error ? error.message : String(error),
    )]
    return null
  }
  if (!decoded || typeof decoded !== 'object' || Array.isArray(decoded)) {
    importErrors.value = [t('extensions.mcpEditJsonObjectRequired')]
    return null
  }
  const server = { ...(decoded as Record<string, unknown>) }
  server.server_id = String(props.item?.payload?.server_id || server.server_id || '')
  return server as unknown as McpServerConfig
}

function manualServer(): McpServerConfig {
  const name = formData.value.display_name.trim()
  const env = formData.value.env.trim()
  const headers = formData.value.headers.trim()
  return {
    server_id: props.item?.payload?.server_id,
    display_name: name,
    description: formData.value.description.trim(),
    transport: formData.value.transport,
    command: formData.value.transport === 'stdio' ? formData.value.command.trim() : undefined,
    args: formData.value.transport === 'stdio' ? formData.value.args.trim() : undefined,
    cwd: formData.value.transport === 'stdio' ? formData.value.cwd.trim() : undefined,
    env: formData.value.transport === 'stdio' && env ? env : undefined,
    url: formData.value.transport !== 'stdio' ? formData.value.url.trim() : undefined,
    headers: formData.value.transport !== 'stdio' && headers ? headers : undefined,
    timeout_seconds: formData.value.timeout_seconds,
    enabled: true,
    risk_level_default: formData.value.risk_level_default,
    source: { type: formData.value.transport === 'stdio' ? 'local' : 'remote', name, description: formData.value.description.trim() || undefined },
  }
}

function normalizeTransport(value: unknown): McpServerConfig['transport'] {
  if (value === 'streamable_http' || value === 'sse') return value
  return 'stdio'
}

function normalizeRiskLevel(value: unknown): NonNullable<McpServerConfig['risk_level_default']> {
  if (value === 'low' || value === 'high') return value
  return 'medium'
}

function serverCommand(server: McpServerConfig): string {
  return server.transport === 'stdio'
    ? [server.command, mcpConfigArgsText(server.args)].filter(Boolean).join(' ')
    : String(server.url || '')
}

function recordKeys(value: string | Record<string, string> | undefined): string {
  const text = mcpConfigRecordText(value)
  return text.split('\n').map(line => line.split('=', 1)[0]?.trim()).filter(Boolean).join(', ')
}

function testStatusLabel(status: unknown): string {
  if (status === 'ok') return t('extensions.connectionOk')
  if (status === 'running') return t('extensions.mcpInstallRunning')
  if (status === 'cancelled') return t('extensions.mcpInstallCancelled')
  return t('extensions.connectionFailed')
}
</script>

<style scoped>
.mode-switch, .import-panel, .preview-list, .test-row { display: grid; gap: var(--app-space-md); }
.mode-switch { margin-bottom: var(--app-space-lg); }
.preview-card { padding: var(--app-space-md); border: 1px solid var(--app-divider); border-radius: var(--app-radius-md); background: var(--app-surface-soft); }
.preview-heading, .preview-meta { display: flex; align-items: center; justify-content: space-between; gap: var(--app-space-md); }
.preview-command { display: block; margin-top: var(--app-space-xs); font-family: var(--app-font-mono); overflow-wrap: anywhere; }
.preview-meta { margin-top: var(--app-space-sm); color: var(--app-text-muted); font-size: var(--app-font-xs); justify-content: flex-start; flex-wrap: wrap; }
.test-row { gap: var(--app-space-xs); margin-top: var(--app-space-xs); }
.test-heading { display: flex; align-items: center; justify-content: space-between; gap: var(--app-space-md); }
</style>
