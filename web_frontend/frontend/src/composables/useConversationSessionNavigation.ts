import { computed } from 'vue'
import { useAgentSessionNavigation } from '@/composables/agent/useAgentSessionNavigation'
import { useCommand } from '@/composables/useCommand'
import { useAgentStore } from '@/stores/agent'
import { useRuntimeStore } from '@/stores/runtime'

type FactoryConversationMode = 'create_agent' | 'evolve_agent'

export function useConversationSessionNavigation() {
  const commands = useCommand()
  const agentStore = useAgentStore()
  const runtimeStore = useRuntimeStore()
  const { startNewAgentSession } = useAgentSessionNavigation()
  const factoryMode = computed<FactoryConversationMode | null>(() => {
    if (runtimeStore.currentMode === 'create_agent') return 'create_agent'
    if (runtimeStore.currentMode === 'evolve_agent') return 'evolve_agent'
    return null
  })
  const canStartNewConversationSession = computed(() => (
    Boolean(agentStore.activeChatPackageId)
    || Boolean(factoryMode.value && !runtimeStore.hasActiveRun)
  ))

  async function startNewConversationSession(): Promise<void> {
    if (!canStartNewConversationSession.value) return
    const packageId = agentStore.activeChatPackageId
    if (packageId) {
      await startNewAgentSession(packageId, { workspaceSelectionConfirmed: false })
      return
    }
    const mode = factoryMode.value
    if (!mode) return
    const evolutionPackageId = mode === 'evolve_agent' ? agentStore.selectedPackageId : null
    runtimeStore.showEmptyFactoryConversation(mode, evolutionPackageId)
    commands.newSession(mode, evolutionPackageId)
  }

  return {
    canStartNewConversationSession,
    startNewConversationSession,
  }
}
