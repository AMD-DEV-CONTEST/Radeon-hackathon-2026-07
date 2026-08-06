import type { ToolPermissionOverrideView, ToolPermissionPolicyView } from '@/types/protocol'
import type { McpServerConfig, SkillConfig, WorkspaceContextInput } from './resourceTypes'
import { packageResourceContextPayload } from './resourceContext'
import { requestEvent, withQuery } from './http'

export const extensionsApi = {
  list: (context?: WorkspaceContextInput) => requestEvent(withQuery('/api/extensions', packageResourceContextPayload(context))),
  setBinding: (
    kind: 'mcp' | 'skill',
    identifier: string,
    enabled: boolean,
    context?: WorkspaceContextInput,
  ) =>
    requestEvent('/api/extensions/bindings', {
      method: 'PUT',
      body: JSON.stringify({
        kind,
        identifier,
        enabled,
        ...packageResourceContextPayload(context),
      }),
    }),
  getMcpConfig: (serverId: string, context?: WorkspaceContextInput) =>
    requestEvent(withQuery(`/api/extensions/mcp/${encodeURIComponent(serverId)}`, packageResourceContextPayload(context))),
  saveMcp: (server: McpServerConfig, context?: WorkspaceContextInput) =>
    requestEvent('/api/extensions/mcp', {
      method: 'POST',
      body: JSON.stringify({ server, ...packageResourceContextPayload(context) }),
    }),
  installMcp: (servers: McpServerConfig[], requestId: string, context?: WorkspaceContextInput) =>
    requestEvent('/api/extensions/mcp/install', {
      method: 'POST',
      body: JSON.stringify({ servers, request_id: requestId, ...packageResourceContextPayload(context) }),
    }),
  testMcp: (serverIdOrConfig: string | McpServerConfig, requestId: string, context?: WorkspaceContextInput) => {
    const payload =
      typeof serverIdOrConfig === 'string'
        ? { server_id: serverIdOrConfig, request_id: requestId, ...packageResourceContextPayload(context) }
        : { server: serverIdOrConfig, request_id: requestId, ...packageResourceContextPayload(context) }
    return requestEvent('/api/extensions/mcp/test', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },
  removeMcp: (serverId: string, context?: WorkspaceContextInput) =>
    requestEvent(withQuery(`/api/extensions/mcp/${encodeURIComponent(serverId)}`, packageResourceContextPayload(context)), {
      method: 'DELETE',
    }),
  saveSkill: (skill: SkillConfig, context?: WorkspaceContextInput) =>
    requestEvent('/api/extensions/skills', {
      method: 'POST',
      body: JSON.stringify({
        skill,
        replace_skill_id: skill.replace_skill_id,
        ...packageResourceContextPayload(context),
      }),
    }),
  removeSkill: (skillId: string, context?: WorkspaceContextInput) =>
    requestEvent(withQuery(`/api/extensions/skills/${encodeURIComponent(skillId)}`, packageResourceContextPayload(context)), {
      method: 'DELETE',
    }),
  skillHubStatus: (context?: WorkspaceContextInput) =>
    requestEvent(withQuery('/api/extensions/skills/skillhub/status', packageResourceContextPayload(context))),
  searchSkillHub: (query: string, context?: WorkspaceContextInput) =>
    requestEvent('/api/extensions/skills/skillhub/search', {
      method: 'POST',
      body: JSON.stringify({ query, ...packageResourceContextPayload(context) }),
    }),
  installSkillHubSkill: (skill: string, context?: WorkspaceContextInput) =>
    requestEvent('/api/extensions/skills/skillhub/install', {
      method: 'POST',
      body: JSON.stringify({ skill, ...packageResourceContextPayload(context) }),
    }),
  updateToolPermissions: (policy: ToolPermissionPolicyView, context?: WorkspaceContextInput) =>
    requestEvent('/api/extensions/tool-permissions', {
      method: 'PUT',
      body: JSON.stringify({ policy, ...packageResourceContextPayload(context) }),
    }),
  setToolPermission: (toolId: string, override: ToolPermissionOverrideView, context?: WorkspaceContextInput) =>
    requestEvent(`/api/extensions/tool-permissions/${encodeURIComponent(toolId)}`, {
      method: 'PATCH',
      body: JSON.stringify({ override, ...packageResourceContextPayload(context) }),
    }),
  resetToolPermission: (toolId: string, context?: WorkspaceContextInput) =>
    requestEvent(withQuery(`/api/extensions/tool-permissions/${encodeURIComponent(toolId)}`, packageResourceContextPayload(context)), {
      method: 'DELETE',
    }),
}
