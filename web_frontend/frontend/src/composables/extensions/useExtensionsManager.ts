import { computed, nextTick, onMounted, ref } from 'vue'
import { useDialog } from 'naive-ui'
import { useCommand } from '@/composables/useCommand'
import { useI18n } from '@/composables/useI18n'
import { useManagedResourceContext } from '@/composables/useManagedResourceContext'
import { useExtensionStore } from '@/stores/extension'
import { useAgentStore } from '@/stores/agent'
import { extensionsApi } from '@/api/extensions'
import type {
  McpServerConfig,
  SkillConfig,
  WorkspaceContextInput,
} from '@/api/resourceTypes'
import type {
  ExtensionItemView,
  ToolPermissionApproval,
  ToolPermissionItemView,
  ToolPermissionMode,
  ToolPermissionOverrideView,
  ToolPermissionPolicyView,
  ToolRiskLevel,
} from '@/types/protocol'

export function useExtensionsManager() {
  const extensionStore = useExtensionStore()
  const agentStore = useAgentStore()
  const commands = useCommand()
  const dialog = useDialog()
  const resourceContext = useManagedResourceContext('system_and_package')
  const { t } = useI18n()

  const showMcpModal = ref(false)
  const showSkillModal = ref(false)
  const editingMcp = ref<ExtensionItemView | null>(null)
  const editingMcpConfig = ref<Record<string, unknown> | null>(null)
  const editingMcpConfigLoading = ref(false)
  const editingSkill = ref<ExtensionItemView | null>(null)
  const busyKey = ref<string | null>(null)
  const skillHubQuery = ref('')
  const mcpInstallResult = ref<Record<string, any> | null>(null)
  const mcpInstallRequestId = ref<string | null>(null)
  const mcpInstallStopping = ref(false)
  const mcpTestRequestId = ref<string | null>(null)
  const mcpTestStopping = ref(false)
  const selectedAssemblyTargetId = ref('system:create_agent')
  const bindingsByTarget = ref<Record<string, { mcp_server_ids: string[]; skill_ids: string[] }>>({})
  const draggingExtension = ref<{ kind: 'mcp' | 'skill'; identifier: string } | null>(null)
  const assemblyBusyTargetId = ref<string | null>(null)
  const mcpInstallDisplayResult = computed<Record<string, any> | null>(() => {
    const liveResult = extensionStore.testResult
    if (
      mcpInstallRequestId.value
      && liveResult?.request_id === mcpInstallRequestId.value
    ) {
      return liveResult
    }
    return mcpInstallResult.value
  })

  const extensionContext = computed(() => resourceContext.workspaceContext.value)
  const assemblyTargets = computed(() => {
    const systemTargets = [
      {
        id: 'system:create_agent',
        packageId: '',
        resourceMode: 'create_agent',
        name: t('resource.manufacturing'),
        glyph: t('extensions.manufacturingGlyph'),
      },
      {
        id: 'system:evolve_agent',
        packageId: '',
        resourceMode: 'evolve_agent',
        name: t('resource.evolution'),
        glyph: t('extensions.evolutionGlyph'),
      },
    ]
    const packages = agentStore.agentPackages.map((pkg) => ({
      id: `package:${pkg.package_id}`,
      packageId: pkg.package_id,
      resourceMode: '',
      name: pkg.agent_name || pkg.name || pkg.package_id,
      glyph: String(pkg.agent_name || pkg.name || pkg.package_id).slice(0, 1).toUpperCase(),
    }))
    return [...systemTargets, ...packages]
  })
  const selectedAssemblyTarget = computed(() => (
    assemblyTargets.value.find((target) => target.id === selectedAssemblyTargetId.value)
      || assemblyTargets.value[0]
      || null
  ))
  const testResultType = computed(() => {
    if (extensionStore.testResult?.status === 'ok') return 'success'
    if (extensionStore.testResult?.status === 'running') return 'info'
    if (extensionStore.testResult?.status === 'cancelled') return 'warning'
    return 'error'
  })
  const testResultTitle = computed(() => {
    if (extensionStore.testResult?.status === 'ok') return t('extensions.connectionOk')
    if (extensionStore.testResult?.status === 'running') return t('extensions.mcpInstallRunning')
    if (extensionStore.testResult?.status === 'cancelled') return t('extensions.mcpInstallCancelled')
    return t('extensions.connectionFailed')
  })
  const toolPermissionPolicy = computed<ToolPermissionPolicyView>(() => (
    extensionStore.toolPermissions?.policy || defaultToolPermissionPolicy()
  ))
  const toolPermissionTools = computed(() => extensionStore.toolPermissions?.tools || [])
  const skillHubItems = computed(() => (
    Array.isArray(extensionStore.skillHubResult?.items) ? extensionStore.skillHubResult.items : []
  ))
  const skillHubCliAvailable = computed(() => extensionStore.skillHubResult?.cli_available === true)
  const skillHubStatusMessage = computed(() => {
    const result = extensionStore.skillHubResult
    if (!result) return t('extensions.skillHubStatusUnknown')
    if (result.action === 'search') {
      const count = Array.isArray(result.items) ? result.items.length : 0
      return t('extensions.skillHubSearchCompleted', { count })
    }
    if (result.cli_available === true) {
      const version = String(result.cli_version || '').trim()
      return version
        ? t('extensions.skillHubAvailableVersion', { version })
        : t('extensions.skillHubAvailable')
    }
    return t('extensions.skillHubMissing')
  })
  const permissionModeOptions = computed(() => [
    { label: t('permissions.mode.strict'), value: 'strict' },
    { label: t('permissions.mode.allowBelowHigh'), value: 'allow_below_high' },
    { label: t('permissions.mode.allowAll'), value: 'allow_all' },
  ])
  const riskLevelOptions = computed(() => [
    { label: t('permissions.risk.low'), value: 'low' },
    { label: t('permissions.risk.medium'), value: 'medium' },
    { label: t('permissions.risk.high'), value: 'high' },
  ])
  const approvalOptions = computed(() => [
    { label: t('permissions.approval.inherit'), value: 'inherit' },
    { label: t('permissions.approval.allow'), value: 'allow' },
    { label: t('permissions.approval.ask'), value: 'ask' },
    { label: t('permissions.approval.deny'), value: 'deny' },
  ])
  const activePermissionModeLabel = computed(() => {
    const match = permissionModeOptions.value.find((option) => option.value === toolPermissionPolicy.value.mode)
    return match?.label || t('permissions.mode.allowBelowHigh')
  })

  function refreshCurrentExtensions() {
    extensionStore.reset()
    editingMcp.value = null
    editingMcpConfig.value = null
    editingMcpConfigLoading.value = false
    editingSkill.value = null
    showMcpModal.value = false
    showSkillModal.value = false
    const refresh = commands.refreshExtensions(extensionContext.value)
    void commands.skillHubStatus(extensionContext.value)
    return refresh
  }

  async function refreshExtensionWorkbench(): Promise<void> {
    await commands.listAgentPackages()
    await nextTick()
    const targets = assemblyTargets.value
    if (!targets.length) return
    if (!targets.some((target) => target.id === selectedAssemblyTargetId.value)) {
      selectedAssemblyTargetId.value = targets[0].id
    }
    const settled = await Promise.allSettled(
      targets.map(async (target) => {
        const response = await extensionsApi.list(assemblyTargetContext(target))
        return {
          targetId: target.id,
          payload: (response as any)?.payload || {},
        }
      }),
    )
    const results = settled.flatMap((result) => (
      result.status === 'fulfilled' ? [result.value] : []
    ))
    bindingsByTarget.value = Object.fromEntries(
      results.map((result) => [
        result.targetId,
        normalizeBindings(result.payload.bindings),
      ]),
    )
    const registryPayload = results[0]?.payload
    if (registryPayload) {
      extensionStore.setItems([
        ...(Array.isArray(registryPayload.mcp_servers) ? registryPayload.mcp_servers : []),
        ...(Array.isArray(registryPayload.skills) ? registryPayload.skills : []),
      ])
    }
    void commands.skillHubStatus(extensionContext.value)
  }

  function startExtensionDrag(kind: 'mcp' | 'skill', identifier: string): void {
    draggingExtension.value = { kind, identifier }
  }

  function finishExtensionDrag(): void {
    draggingExtension.value = null
  }

  async function dropExtensionOnTarget(targetId: string): Promise<void> {
    const dragged = draggingExtension.value
    const target = assemblyTargets.value.find((item) => item.id === targetId)
    if (!dragged || !target || assemblyBusyTargetId.value) return
    assemblyBusyTargetId.value = targetId
    selectedAssemblyTargetId.value = targetId
    try {
      await commands.setExtensionBinding(
        dragged.kind,
        dragged.identifier,
        true,
        assemblyTargetContext(target),
      )
      await refreshTargetBindings(target)
    } finally {
      assemblyBusyTargetId.value = null
      finishExtensionDrag()
    }
  }

  async function removeExtensionFromTarget(
    targetId: string,
    kind: 'mcp' | 'skill',
    identifier: string,
  ): Promise<void> {
    const target = assemblyTargets.value.find((item) => item.id === targetId)
    if (!target || assemblyBusyTargetId.value) return
    assemblyBusyTargetId.value = targetId
    try {
      await commands.setExtensionBinding(
        kind,
        identifier,
        false,
        assemblyTargetContext(target),
      )
      await refreshTargetBindings(target)
    } finally {
      assemblyBusyTargetId.value = null
    }
  }

  function targetExtensions(targetId: string): ExtensionItemView[] {
    const bindings = bindingsByTarget.value[targetId] || normalizeBindings(null)
    const mcpIds = new Set(bindings.mcp_server_ids)
    const skillIds = new Set(bindings.skill_ids)
    return extensionStore.items.filter((item) => (
      item.kind === 'mcp'
        ? mcpIds.has(String(item.payload?.server_id || ''))
        : skillIds.has(String(item.payload?.skill_id || ''))
    ))
  }

  function targetExtensionCount(targetId: string): number {
    const bindings = bindingsByTarget.value[targetId] || normalizeBindings(null)
    return bindings.mcp_server_ids.length + bindings.skill_ids.length
  }

  async function refreshTargetBindings(target: any): Promise<void> {
    const response = await extensionsApi.list(assemblyTargetContext(target))
    const payload = (response as any)?.payload || {}
    bindingsByTarget.value = {
      ...bindingsByTarget.value,
      [target.id]: normalizeBindings(payload.bindings),
    }
  }

  async function handleSkillHubSearch(): Promise<void> {
    const query = skillHubQuery.value.trim()
    if (!query || busyKey.value) return
    busyKey.value = 'skillhub:search'
    try {
      await commands.searchSkillHub(query, extensionContext.value)
    } finally {
      busyKey.value = null
    }
  }

  async function handleSkillHubInstall(item: any): Promise<void> {
    const skill = String(item?.install_name || item?.skill || item?.name || '').trim()
    if (!skill || busyKey.value) return
    busyKey.value = `skillhub:install:${skill}`
    try {
      const event = await commands.installSkillHubSkill(skill, extensionContext.value)
      if (event) await refreshExtensionWorkbench()
    } finally {
      busyKey.value = null
    }
  }

  function openAddMcp(): void {
    editingMcp.value = null
    editingMcpConfig.value = null
    editingMcpConfigLoading.value = false
    mcpInstallResult.value = null
    showMcpModal.value = true
  }

  async function openEditMcp(item: ExtensionItemView): Promise<void> {
    const serverId = String(item.payload?.server_id || '')
    if (!serverId) return
    editingMcp.value = item
    editingMcpConfig.value = null
    editingMcpConfigLoading.value = true
    mcpInstallResult.value = null
    showMcpModal.value = true
    try {
      const event = await commands.getMcpConfig(serverId, extensionContext.value)
      if (String(editingMcp.value?.payload?.server_id || '') !== serverId) return
      const config = event?.payload?.server_config
      editingMcpConfig.value = config && typeof config === 'object' && !Array.isArray(config)
        ? config as Record<string, unknown>
        : null
    } finally {
      if (String(editingMcp.value?.payload?.server_id || '') === serverId) {
        editingMcpConfigLoading.value = false
      }
    }
  }

  function openAddSkill(): void {
    editingSkill.value = null
    showSkillModal.value = true
  }

  function openEditSkill(item: ExtensionItemView): void {
    editingSkill.value = item
    showSkillModal.value = true
  }

  async function handleTestMcp(item: ExtensionItemView): Promise<void> {
    const serverId = String(item.payload?.server_id || '')
    if (!serverId || busyKey.value) return
    const requestId = crypto.randomUUID()
    busyKey.value = `test:${extensionKey(item)}`
    mcpTestRequestId.value = requestId
    mcpTestStopping.value = false
    extensionStore.setTestResult(null)
    try {
      await commands.testMcp(serverId, requestId, extensionContext.value)
    } finally {
      mcpTestRequestId.value = null
      mcpTestStopping.value = false
      busyKey.value = null
    }
  }

  function handleStopMcpTest(): void {
    const requestId = mcpTestRequestId.value
    if (!requestId || mcpTestStopping.value) return
    mcpTestStopping.value = true
    commands.cancelRequest('user_cancelled', requestId)
  }

  async function handleInstallMcp(servers: McpServerConfig[]): Promise<void> {
    if (busyKey.value || servers.length === 0) return
    busyKey.value = 'mcp:install'
    mcpInstallResult.value = null
    extensionStore.setTestResult(null)
    const requestId = crypto.randomUUID()
    mcpInstallRequestId.value = requestId
    mcpInstallStopping.value = false
    try {
      const event = await commands.installMcp(servers, requestId, extensionContext.value)
      const install = event?.payload?.install
      mcpInstallResult.value = install && typeof install === 'object' ? install : null
      if (mcpInstallResult.value?.status !== 'ok') return
      showMcpModal.value = false
      editingMcp.value = null
      editingMcpConfig.value = null
      await refreshExtensionWorkbench()
    } finally {
      mcpInstallRequestId.value = null
      mcpInstallStopping.value = false
      busyKey.value = null
    }
  }

  function handleStopMcpInstall(): void {
    const requestId = mcpInstallRequestId.value
    if (!requestId || mcpInstallStopping.value) return
    mcpInstallStopping.value = true
    commands.cancelRequest('user_cancelled', requestId)
  }

  async function handleSaveSkill(config: SkillConfig): Promise<void> {
    const event = await commands.saveSkill(config, extensionContext.value)
    if (event) {
      showSkillModal.value = false
      editingSkill.value = null
      await refreshExtensionWorkbench()
    }
  }

  async function handlePermissionModeChange(mode: string): Promise<void> {
    const nextMode = normalizePermissionMode(mode)
    busyKey.value = 'tool-permissions:mode'
    try {
      await commands.updateToolPermissions(
        { mode: nextMode, tool_overrides: toolPermissionPolicy.value.tool_overrides || {} },
        extensionContext.value,
      )
    } finally {
      busyKey.value = null
    }
  }

  async function handleToolRiskChange(tool: ToolPermissionItemView, riskLevel: string): Promise<void> {
    const override = toolOverride(tool.tool_id)
    await saveToolOverride(tool.tool_id, { ...override, risk_level: normalizeRiskLevel(riskLevel) })
  }

  async function handleToolApprovalChange(tool: ToolPermissionItemView, approval: string): Promise<void> {
    const override = toolOverride(tool.tool_id)
    await saveToolOverride(tool.tool_id, { ...override, approval: normalizeApproval(approval) })
  }

  async function handleResetToolPermission(tool: ToolPermissionItemView): Promise<void> {
    busyKey.value = `permission:${tool.tool_id}`
    try {
      await commands.resetToolPermission(tool.tool_id, extensionContext.value)
    } finally {
      busyKey.value = null
    }
  }

  async function saveToolOverride(toolId: string, override: ToolPermissionOverrideView): Promise<void> {
    busyKey.value = `permission:${toolId}`
    try {
      await commands.setToolPermission(toolId, override, extensionContext.value)
    } finally {
      busyKey.value = null
    }
  }

  function handleMcpAction(key: string, item: ExtensionItemView): void {
    if (key === 'edit') {
      openEditMcp(item)
      return
    }
    if (key === 'remove') {
      confirmRemoveMcp(item)
    }
  }

  function handleSkillAction(key: string, item: ExtensionItemView): void {
    if (key === 'edit') {
      openEditSkill(item)
      return
    }
    if (key === 'remove') {
      confirmRemoveSkill(item)
    }
  }

  function confirmRemoveMcp(item: ExtensionItemView): void {
    const serverId = String(item.payload?.server_id || '')
    if (!serverId) return
    dialog.warning({
      title: t('extensions.deleteMcpTitle'),
      content: removalConfirmation(
        item,
        t('extensions.deleteMcpContent', {
          name: item.name || t('extensions.thisMcpServer'),
        }),
      ),
      positiveText: t('common.delete'),
      negativeText: t('common.cancel'),
      onPositiveClick: async () => {
        await commands.removeMcp(serverId, extensionContext.value)
        await refreshExtensionWorkbench()
      },
    })
  }

  function confirmRemoveSkill(item: ExtensionItemView): void {
    const skillId = String(item.payload?.skill_id || '')
    if (!skillId) return
    dialog.warning({
      title: t('extensions.deleteSkillTitle'),
      content: removalConfirmation(
        item,
        t('extensions.deleteSkillContent', {
          name: item.name || t('extensions.thisSkill'),
        }),
      ),
      positiveText: t('common.delete'),
      negativeText: t('common.cancel'),
      onPositiveClick: async () => {
        await commands.removeSkill(skillId, extensionContext.value)
        await refreshExtensionWorkbench()
      },
    })
  }

  function extensionUsageCount(item: ExtensionItemView): number {
    const identifier = extensionKey(item)
    return Object.values(bindingsByTarget.value).filter((bindings) => (
      item.kind === 'mcp'
        ? bindings.mcp_server_ids.includes(identifier)
        : bindings.skill_ids.includes(identifier)
    )).length
  }

  function removalConfirmation(item: ExtensionItemView, base: string): string {
    const count = extensionUsageCount(item)
    if (!count) return base
    return `${base}\n${t('extensions.usedByAgentsWarning', { count })}`
  }

  onMounted(() => {
    void refreshExtensionWorkbench()
  })

  const mcpActions = computed(() => [
    { label: t('common.edit'), key: 'edit' },
    { label: t('common.delete'), key: 'remove' },
  ])

  const skillActions = computed(() => [
    { label: t('common.edit'), key: 'edit' },
    { label: t('common.delete'), key: 'remove' },
  ])

  function mcpCommandLine(item: ExtensionItemView): string {
    const url = String(item.payload?.url || '')
    if (url) return url
    const command = String(item.payload?.command || '')
    const args = Array.isArray(item.payload?.args)
      ? item.payload.args.join(' ')
      : String(item.payload?.args || '')
    return [command, args].filter(Boolean).join(' ') || t('extensions.commandUnset')
  }

  function toolOverride(toolId: string): ToolPermissionOverrideView {
    return toolPermissionPolicy.value.tool_overrides?.[toolId] || { approval: 'inherit', risk_level: null }
  }

  function toolRiskValue(tool: ToolPermissionItemView): ToolRiskLevel {
    return toolOverride(tool.tool_id).risk_level || tool.risk_level
  }

  function toolApprovalValue(tool: ToolPermissionItemView): ToolPermissionApproval {
    return toolOverride(tool.tool_id).approval || 'inherit'
  }

  function hasToolOverride(tool: ToolPermissionItemView): boolean {
    return Boolean(toolPermissionPolicy.value.tool_overrides?.[tool.tool_id])
  }

  function toolSourceLabel(source: string): string {
    if (source === 'system') return t('permissions.source.system')
    if (source === 'extension') return t('permissions.source.extension')
    if (source === 'model') return t('permissions.source.model')
    return t('permissions.source.package')
  }

  return {
    activePermissionModeLabel,
    agentStore,
    assemblyBusyTargetId,
    assemblyTargets,
    bindingsByTarget,
    busyKey,
    editingMcp,
    editingMcpConfig,
    editingMcpConfigLoading,
    editingSkill,
    extensionKey,
    extensionStore,
    draggingExtension,
    resourceContext,
    handleMcpAction,
    handleInstallMcp,
    handleStopMcpInstall,
    handleStopMcpTest,
    handleSaveSkill,
    handleSkillHubInstall,
    handleSkillHubSearch,
    handleSkillAction,
    handleTestMcp,
    dropExtensionOnTarget,
    finishExtensionDrag,
    mcpActions,
    mcpCommandLine,
    mcpInstallDisplayResult,
    mcpInstallStopping,
    mcpTestStopping,
    openAddMcp,
    openAddSkill,
    permissionModeOptions,
    refreshCurrentExtensions,
    refreshExtensionWorkbench,
    removeExtensionFromTarget,
    approvalOptions,
    handlePermissionModeChange,
    handleResetToolPermission,
    handleToolApprovalChange,
    handleToolRiskChange,
    hasToolOverride,
    riskLevelOptions,
    showMcpModal,
    showSkillModal,
    selectedAssemblyTarget,
    selectedAssemblyTargetId,
    skillActions,
    skillHubCliAvailable,
    skillHubItems,
    skillHubQuery,
    skillHubStatusMessage,
    toolApprovalValue,
    toolPermissionPolicy,
    toolPermissionTools,
    toolRiskValue,
    toolSourceLabel,
    testResultTitle,
    testResultType,
    startExtensionDrag,
    targetExtensionCount,
    targetExtensions,
  }
}

function assemblyTargetContext(target: any): WorkspaceContextInput {
  if (target?.resourceMode) return { resourceMode: target.resourceMode }
  return { packageId: String(target?.packageId || '') }
}

function normalizeBindings(value: any): { mcp_server_ids: string[]; skill_ids: string[] } {
  return {
    mcp_server_ids: Array.isArray(value?.mcp_server_ids) ? value.mcp_server_ids.map(String) : [],
    skill_ids: Array.isArray(value?.skill_ids) ? value.skill_ids.map(String) : [],
  }
}

function extensionKey(item: ExtensionItemView): string {
  return String(item.payload?.server_id || item.payload?.skill_id || item.name || item.kind)
}

function defaultToolPermissionPolicy(): ToolPermissionPolicyView {
  return {
    mode: 'allow_below_high',
    low: 'allow',
    medium: 'allow',
    high: 'ask',
    tool_overrides: {},
  }
}

function normalizePermissionMode(value: string): ToolPermissionMode {
  if (value === 'strict' || value === 'allow_all' || value === 'custom') return value
  return 'allow_below_high'
}

function normalizeRiskLevel(value: string): ToolRiskLevel {
  if (value === 'medium' || value === 'high') return value
  return 'low'
}

function normalizeApproval(value: string): ToolPermissionApproval {
  if (value === 'allow' || value === 'ask' || value === 'deny') return value
  return 'inherit'
}
