import * as commands from '@/api/commands'
import { agentPackagesApi } from '@/api/agentPackages'
import { useAgentStore, type AgentPackageView } from '@/stores/agent'
import { useRuntimeStore } from '@/stores/runtime'
import { useUiStore } from '@/stores/ui'
import { useI18n } from '@/composables/useI18n'
import type { RuntimeAttachmentInput } from '@/types/protocol'
import { useCommandTransport } from './transport'

export function useAgentPackageCommands() {
  const agentStore = useAgentStore()
  const runtimeStore = useRuntimeStore()
  const uiStore = useUiStore()
  const transport = useCommandTransport()
  const { t } = useI18n()

  const listAgentPackages = () => {
    transport.applyEventRequest(agentPackagesApi.list())
  }

  const selectAgentPackage = (packageId: string, purpose?: 'run' | 'evolution') => {
    runtimeStore.expectAgentPackageSelection(packageId, purpose || 'run')
    return transport.applyEventRequest(agentPackagesApi.select(packageId, purpose))
  }

  const deleteAgentPackage = (packageId: string) => {
    return transport.applyEventRequest(agentPackagesApi.delete(packageId))
  }

  const exportAgentPackage = async (pkg: AgentPackageView) => {
    try {
      const response = await agentPackagesApi.exportArchive(pkg.package_id)
      const url = URL.createObjectURL(response.blob)
      const link = document.createElement('a')
      link.href = url
      link.download = response.filename || `${pkg.agent_name || pkg.name || pkg.package_id}.zip`
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
      uiStore.addNotification({
        type: 'success',
        title: t('agents.exportCompleteTitle'),
        message: t('agents.exportCompleteMessage', { name: pkg.agent_name || pkg.name || t('common.unnamedAgent') }),
        duration: 3000,
      })
      return true
    } catch (error) {
      transport.reportError(error)
      return false
    }
  }

  const listAgentPackageSessions = (packageId: string) => {
    return transport.applyEventRequest(agentPackagesApi.sessions(packageId))
  }

  const listAgentPackageInstances = () => {
    return transport.applyEventRequest(agentPackagesApi.instances())
  }

  const listRecentAgentSessions = async (limit = 5) => {
    try {
      const response = await agentPackagesApi.recentSessions(limit)
      agentStore.setRecentSessions(response.sessions)
      return response.sessions
    } catch (error) {
      transport.reportError(error)
      return []
    }
  }

  const initializeAgentPackage = (packageId: string) => {
    return transport.applyEventRequest(agentPackagesApi.initialize(packageId))
  }

  const shutdownAgentPackageInstance = (packageId: string) => {
    return transport.applyEventRequest(agentPackagesApi.shutdown(packageId))
  }

  const loadAgentPackageSession = (
    packageId: string,
    sessionId: string,
  ) => {
    runtimeStore.expectAgentPackageSession(packageId, sessionId)
    return transport.applyEventRequest(agentPackagesApi.session(packageId, sessionId))
  }

  const deleteAgentPackageSession = (packageId: string, sessionId: string) => {
    return transport.applyEventRequest(agentPackagesApi.deleteSession(packageId, sessionId))
  }

  const runAgentPackage = (
    packageId: string,
    message: string,
    sessionId?: string,
    attachments?: RuntimeAttachmentInput[],
    runtimeOptions?: commands.RuntimeMainModelOptions,
    displayUserInput?: string | null,
  ) => {
    const command = commands.runAgentPackageCommand(packageId, message, sessionId, attachments, runtimeOptions, displayUserInput)
    transport.sendRuntimeCommand(command)
    return command
  }

  const sendAgentPackageMessage = (
    packageId: string,
    message: string,
    sessionId?: string,
    attachments?: RuntimeAttachmentInput[],
    runtimeOptions?: commands.RuntimeMainModelOptions,
    displayUserInput?: string | null,
    workspaceId?: string | null,
  ) => {
    const command = commands.sendAgentPackageMessageCommand(
      packageId,
      message,
      sessionId,
      attachments,
      runtimeOptions,
      displayUserInput,
      workspaceId,
    )
    transport.sendRuntimeCommand(command)
    return command
  }

  const runAgentEvolution = (
    packageId: string,
    message: string,
    attachments?: RuntimeAttachmentInput[],
    runtimeOptions?: commands.RuntimeMainModelOptions,
  ) => {
    const command = commands.runAgentEvolutionCommand(
      packageId,
      message,
      attachments,
      runtimeOptions,
      runtimeStore.activeFactorySessionId,
    )
    transport.sendRuntimeCommand(command)
    return command
  }

  return {
    listAgentPackages,
    selectAgentPackage,
    deleteAgentPackage,
    exportAgentPackage,
    listAgentPackageSessions,
    listAgentPackageInstances,
    listRecentAgentSessions,
    initializeAgentPackage,
    shutdownAgentPackageInstance,
    loadAgentPackageSession,
    deleteAgentPackageSession,
    runAgentPackage,
    sendAgentPackageMessage,
    runAgentEvolution,
  }
}
