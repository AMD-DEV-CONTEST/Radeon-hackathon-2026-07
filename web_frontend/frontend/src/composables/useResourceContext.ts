import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useAgentGroupStore } from '@/stores/agentGroup'
import { useAgentStore } from '@/stores/agent'
import { useRuntimeStore } from '@/stores/runtime'
import { useI18n } from '@/composables/useI18n'
import { SYSTEM_CHAT_PACKAGE_ID } from '@/utils/resourceScope'
import type { WorkspaceRequestContext, WorkspaceScope } from '@/api/resourceTypes'

export function useResourceContext() {
  const agentStore = useAgentStore()
  const agentGroupStore = useAgentGroupStore()
  const runtimeStore = useRuntimeStore()
  const route = useRoute()
  const { t } = useI18n()

  const packageId = computed(() => {
    if (agentStore.activeChatPackageId) return agentStore.activeChatPackageId
    if (runtimeStore.currentMode === 'evolve_agent' && agentStore.selectedPackageId) {
      return agentStore.selectedPackageId
    }
    return null
  })

  const packageInfo = computed(() => {
    if (!packageId.value) return null
    return agentStore.agentPackages.find((pkg) => pkg.package_id === packageId.value) || null
  })

  const activeFactorySession = computed(() => (
    runtimeStore.sessions.find((session: any) => session.session_id === runtimeStore.activeFactorySessionId) || null
  ))
  const createAgentSessionId = computed(() => (
    String(activeFactorySession.value?.create_agent_session_id || '').trim() || null
  ))
  const workspaceContext = computed<WorkspaceRequestContext>(() => {
    if (route.name === 'AgentGroup' && agentGroupStore.activeGroup?.group_id) {
      return { resourceMode: 'agent_group', groupId: agentGroupStore.activeGroup.group_id }
    }
    if (runtimeStore.currentMode === 'create_agent') {
      return {
        resourceMode: 'create_agent',
        factorySessionId: runtimeStore.activeFactorySessionId,
        createAgentSessionId: createAgentSessionId.value,
      }
    }
    if (runtimeStore.currentMode === 'evolve_agent') {
      return {
        resourceMode: 'evolve_agent',
        packageId: agentStore.selectedPackageId,
        factorySessionId: runtimeStore.activeFactorySessionId,
      }
    }
    if (agentStore.activeChatPackageId) {
      return {
        resourceMode: 'package',
        packageId: agentStore.activeChatPackageId,
        packageSessionId: agentStore.selectedSessionId || runtimeStore.activeAgentSessionId,
        workspaceId: runtimeStore.activeWorkspaceId,
      }
    }
    return {
      resourceMode: 'package',
      packageId: SYSTEM_CHAT_PACKAGE_ID,
      packageSessionId: runtimeStore.activeAgentSessionId,
    }
  })
  const workspaceContextKey = computed(() => [
    workspaceContext.value.resourceMode || '',
    workspaceContext.value.packageId || '',
    workspaceContext.value.packageSessionId || '',
    workspaceContext.value.workspaceId || '',
    workspaceContext.value.factorySessionId || '',
    workspaceContext.value.createAgentSessionId || '',
    workspaceContext.value.groupId || '',
  ].join(':'))
  const workspaceDefaultScope = computed<WorkspaceScope>(() => 'workdir')
  const workspaceAvailable = computed(() => (
    workspaceContext.value.resourceMode !== 'package'
    || Boolean(workspaceContext.value.packageSessionId || workspaceContext.value.workspaceId)
  ))
  const packageIdForApi = computed(() => packageId.value || SYSTEM_CHAT_PACKAGE_ID)
  const isAgentSessionContext = computed(() => (
    runtimeStore.currentMode === 'agent_package'
    && Boolean(agentStore.activeChatPackageId)
  ))
  const label = computed(() => {
    if (workspaceContext.value.resourceMode === 'agent_group') return agentGroupStore.activeGroup?.title || 'Agent Group'
    if (runtimeStore.currentMode === 'create_agent') return t('resource.manufacturing')
    if (!packageId.value) return t('resource.chat')
    const pkg = packageInfo.value
    const prefix = runtimeStore.currentMode === 'evolve_agent' ? t('resource.evolution') : t('resource.subAgent')
    return `${prefix} · ${pkg?.agent_name || pkg?.name || t('common.unnamedAgent')}`
  })

  return {
    packageId,
    packageIdForApi,
    packageInfo,
    isAgentSessionContext,
    label,
    workspaceContext,
    workspaceContextKey,
    workspaceDefaultScope,
    workspaceAvailable,
  }
}
