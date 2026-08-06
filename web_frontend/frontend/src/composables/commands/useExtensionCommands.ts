import { extensionsApi } from '@/api/extensions'
import type { ToolPermissionOverrideView, ToolPermissionPolicyView } from '@/types/protocol'
import type { McpServerConfig, SkillConfig, WorkspaceContextInput } from '@/api/resourceTypes'
import { useCommandTransport } from './transport'

export function useExtensionCommands() {
  const transport = useCommandTransport()

  const refreshExtensions = (context?: WorkspaceContextInput) => {
    return transport.applyEventRequest(extensionsApi.list(context))
  }

  const setExtensionBinding = (
    kind: 'mcp' | 'skill',
    identifier: string,
    enabled: boolean,
    context?: WorkspaceContextInput,
  ) => {
    return transport.applyEventRequest(
      extensionsApi.setBinding(kind, identifier, enabled, context),
    )
  }

  const getMcpConfig = (serverId: string, context?: WorkspaceContextInput) => {
    return transport.applyEventRequest(extensionsApi.getMcpConfig(serverId, context))
  }

  const saveMcp = (server: McpServerConfig, context?: WorkspaceContextInput) => {
    return transport.applyEventRequest(extensionsApi.saveMcp(server, context))
  }

  const installMcp = (servers: McpServerConfig[], requestId: string, context?: WorkspaceContextInput) => {
    return transport.applyEventRequest(extensionsApi.installMcp(servers, requestId, context))
  }

  const testMcp = (serverIdOrConfig: string | McpServerConfig, requestId: string, context?: WorkspaceContextInput) => {
    return transport.applyEventRequest(extensionsApi.testMcp(serverIdOrConfig, requestId, context))
  }

  const removeMcp = (serverId: string, context?: WorkspaceContextInput) => {
    return transport.applyEventRequest(extensionsApi.removeMcp(serverId, context))
  }

  const saveSkill = (skill: SkillConfig, context?: WorkspaceContextInput) => {
    return transport.applyEventRequest(extensionsApi.saveSkill(skill, context))
  }

  const removeSkill = (skillId: string, context?: WorkspaceContextInput) => {
    return transport.applyEventRequest(extensionsApi.removeSkill(skillId, context))
  }

  const skillHubStatus = (context?: WorkspaceContextInput) => {
    return transport.applyEventRequest(extensionsApi.skillHubStatus(context))
  }

  const searchSkillHub = (query: string, context?: WorkspaceContextInput) => {
    return transport.applyEventRequest(extensionsApi.searchSkillHub(query, context))
  }

  const installSkillHubSkill = (skill: string, context?: WorkspaceContextInput) => {
    return transport.applyEventRequest(extensionsApi.installSkillHubSkill(skill, context))
  }

  const updateToolPermissions = (policy: ToolPermissionPolicyView, context?: WorkspaceContextInput) => {
    return transport.applyEventRequest(extensionsApi.updateToolPermissions(policy, context))
  }

  const setToolPermission = (toolId: string, override: ToolPermissionOverrideView, context?: WorkspaceContextInput) => {
    return transport.applyEventRequest(extensionsApi.setToolPermission(toolId, override, context))
  }

  const resetToolPermission = (toolId: string, context?: WorkspaceContextInput) => {
    return transport.applyEventRequest(extensionsApi.resetToolPermission(toolId, context))
  }

  return {
    refreshExtensions,
    setExtensionBinding,
    getMcpConfig,
    saveMcp,
    installMcp,
    testMcp,
    removeMcp,
    saveSkill,
    removeSkill,
    skillHubStatus,
    searchSkillHub,
    installSkillHubSkill,
    updateToolPermissions,
    setToolPermission,
    resetToolPermission,
  }
}
