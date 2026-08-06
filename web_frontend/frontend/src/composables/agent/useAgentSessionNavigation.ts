import { useRouter } from 'vue-router'
import { useCommand } from '@/composables/useCommand'
import { useAgentStore, type AgentRecentSessionView } from '@/stores/agent'
import {
  agentSessionsLandingQuery,
  newAgentSessionQuery,
  type NewAgentSessionRouteOptions,
} from '@/utils/agentSessionRoute'

export function useAgentSessionNavigation() {
  const router = useRouter()
  const commands = useCommand()
  const agentStore = useAgentStore()

  async function openAgentSession(session: AgentRecentSessionView): Promise<void> {
    const packageId = String(session.package_id || '').trim()
    const sessionId = String(session.session_id || '').trim()
    if (!packageId || !sessionId) return
    await router.push({
      name: 'Factory',
      query: { package_id: packageId, session_id: sessionId },
    })
  }

  async function startNewAgentSession(
    packageId: string,
    options: Omit<NewAgentSessionRouteOptions, 'packageId'> = {},
  ): Promise<void> {
    const normalizedPackageId = String(packageId || '').trim()
    if (!normalizedPackageId) return
    await router.push({
      name: 'Factory',
      query: newAgentSessionQuery({
        packageId: normalizedPackageId,
        workspaceId: options.workspaceId,
        workspaceSelectionConfirmed: options.workspaceSelectionConfirmed,
      }),
    })
  }

  async function openPackageAgentChat(packageId: string): Promise<void> {
    const normalizedPackageId = String(packageId || '').trim()
    if (!normalizedPackageId) return
    await router.push({ name: 'Factory', query: { package_id: normalizedPackageId } })
  }

  async function openMostRecentAgentSession(): Promise<boolean> {
    await commands.listRecentAgentSessions(20)
    const preferred = agentStore.preferredRecentSession()
    if (!preferred) return false
    await openAgentSession(preferred)
    return true
  }

  async function openAgentSessions(): Promise<void> {
    const opened = await openMostRecentAgentSession()
    if (opened) return
    await router.push({ name: 'Factory', query: agentSessionsLandingQuery() })
  }

  return {
    openAgentSessions,
    openAgentSession,
    openMostRecentAgentSession,
    openPackageAgentChat,
    startNewAgentSession,
  }
}
