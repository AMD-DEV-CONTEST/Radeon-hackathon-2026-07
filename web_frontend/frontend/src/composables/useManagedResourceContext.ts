import { computed, watch } from 'vue'
import { useAgentStore } from '@/stores/agent'
import { useResourceTargetStore } from '@/stores/resourceTarget'
import { useI18n } from '@/composables/useI18n'
import { useResourceContext } from '@/composables/useResourceContext'
import { SYSTEM_CHAT_PACKAGE_ID } from '@/utils/resourceScope'
import type { WorkspaceRequestContext } from '@/api/resourceTypes'
import {
  parseResourceTargetKey,
  resourceTargetFromContext,
  resourceTargetKey,
  type ResourceTarget,
  type ResourceTargetCapability,
  type ResourceTargetOptionGroup,
} from '@/types/resourceTarget'

const FOLLOW_CONTEXT_VALUE = 'context'

export function useManagedResourceContext(capability: ResourceTargetCapability) {
  const inferred = useResourceContext()
  const agentStore = useAgentStore()
  const targetStore = useResourceTargetStore()
  const { t } = useI18n()

  const inferredContextKey = computed(() => contextIdentityKey(inferred.workspaceContext.value))

  watch(
    inferredContextKey,
    (contextKey) => targetStore.synchronizeContext(contextKey),
    { immediate: true },
  )

  const inferredTarget = computed<ResourceTarget>(() => {
    const target = resourceTargetFromContext(inferred.workspaceContext.value)
    if (capability === 'system_and_package') return target || { kind: 'chat' }
    if (target?.kind === 'package' || target?.kind === 'chat') return target
    if (target?.kind === 'evolve_agent' && target.packageId) {
      return { kind: 'package', packageId: target.packageId }
    }
    return { kind: 'chat' }
  })

  const selectedTarget = computed<ResourceTarget>(() => {
    const explicit = targetStore.explicitTarget
    return explicit && targetAllowed(explicit, capability)
      ? explicit
      : inferredTarget.value
  })

  const selectedValue = computed({
    get: () => (
      targetStore.explicitTarget && targetAllowed(targetStore.explicitTarget, capability)
        ? resourceTargetKey(targetStore.explicitTarget)
        : FOLLOW_CONTEXT_VALUE
    ),
    set: (value: string) => {
      if (value === FOLLOW_CONTEXT_VALUE) {
        targetStore.selectTarget(null)
        return
      }
      const target = parseResourceTargetKey(value)
      if (target && targetAllowed(target, capability)) {
        targetStore.selectTarget(target)
      }
    },
  })

  const workspaceContext = computed<WorkspaceRequestContext>(() => (
    selectedValue.value === FOLLOW_CONTEXT_VALUE && contextAllowed(inferred.workspaceContext.value, capability)
      ? inferred.workspaceContext.value
      : workspaceContextForTarget(selectedTarget.value)
  ))

  const workspaceContextKey = computed(() => [
    workspaceContext.value.resourceMode || '',
    workspaceContext.value.packageId || '',
    workspaceContext.value.packageSessionId || '',
    workspaceContext.value.factorySessionId || '',
    workspaceContext.value.createAgentSessionId || '',
    workspaceContext.value.groupId || '',
  ].join(':'))

  const packageId = computed(() => (
    selectedTarget.value.kind === 'package' ? selectedTarget.value.packageId || null : null
  ))
  const packageIdForApi = computed(() => packageId.value || SYSTEM_CHAT_PACKAGE_ID)
  const label = computed(() => targetLabel(selectedTarget.value))
  const targetOptions = computed<ResourceTargetOptionGroup[]>(() => {
    const groups: ResourceTargetOptionGroup[] = [{
      type: 'group',
      label: t('resource.contextGroup'),
      key: 'context',
      children: [{
        label: t('resource.followContext', { label: targetLabel(inferredTarget.value) }),
        value: FOLLOW_CONTEXT_VALUE,
      }],
    }]
    const systemTargets: ResourceTarget[] = capability === 'system_and_package'
      ? [{ kind: 'chat' }, { kind: 'create_agent' }, { kind: 'evolve_agent' }]
      : [{ kind: 'chat' }]
    groups.push({
      type: 'group',
      label: t('resource.systemAgents'),
      key: 'system',
      children: systemTargets.map((target) => ({
        label: targetLabel(target),
        value: resourceTargetKey(target),
      })),
    })
    if (agentStore.agentPackages.length > 0) {
      groups.push({
        type: 'group',
        label: t('resource.publishedAgents'),
        key: 'packages',
        children: agentStore.agentPackages.map((pkg) => ({
          label: pkg.agent_name || pkg.name || pkg.package_id,
          value: resourceTargetKey({ kind: 'package', packageId: pkg.package_id }),
        })),
      })
    }
    return groups
  })

  function targetLabel(target: ResourceTarget): string {
    if (target.kind === 'chat') return t('resource.chat')
    if (target.kind === 'create_agent') return t('resource.manufacturing')
    if (target.kind === 'evolve_agent') return t('resource.evolution')
    const pkg = agentStore.agentPackages.find((item) => item.package_id === target.packageId)
    return pkg?.agent_name || pkg?.name || target.packageId || t('common.unnamedAgent')
  }

  return {
    isFollowingContext: computed(() => selectedValue.value === FOLLOW_CONTEXT_VALUE),
    label,
    packageId,
    packageIdForApi,
    selectedTarget,
    selectedValue,
    targetOptions,
    workspaceContext,
    workspaceContextKey,
  }
}

function targetAllowed(target: ResourceTarget, capability: ResourceTargetCapability): boolean {
  return capability === 'system_and_package' || target.kind === 'chat' || target.kind === 'package'
}

function contextAllowed(context: WorkspaceRequestContext, capability: ResourceTargetCapability): boolean {
  if (capability === 'system_and_package') {
    return context.resourceMode !== 'agent_group'
  }
  return context.resourceMode === 'package' || !context.resourceMode
}

function workspaceContextForTarget(target: ResourceTarget): WorkspaceRequestContext {
  if (target.kind === 'package') {
    return { resourceMode: 'package', packageId: target.packageId }
  }
  if (target.kind === 'create_agent' || target.kind === 'evolve_agent') {
    return { resourceMode: target.kind }
  }
  return { resourceMode: 'package', packageId: SYSTEM_CHAT_PACKAGE_ID }
}

function contextIdentityKey(context: WorkspaceRequestContext): string {
  if (context.resourceMode === 'package' || !context.resourceMode) {
    return `package:${context.packageId || SYSTEM_CHAT_PACKAGE_ID}`
  }
  if (context.resourceMode === 'create_agent') {
    return `create_agent:${context.factorySessionId || ''}:${context.createAgentSessionId || ''}`
  }
  if (context.resourceMode === 'evolve_agent') {
    return `evolve_agent:${context.packageId || ''}:${context.factorySessionId || ''}`
  }
  return `agent_group:${context.groupId || ''}`
}
