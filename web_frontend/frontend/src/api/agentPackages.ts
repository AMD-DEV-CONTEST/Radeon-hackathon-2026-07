import { requestBlob, requestEvent, requestJson, withQuery } from './http'

interface RecentAgentSessionsResponse {
  sessions: any[]
}

interface AgentPackageConfigurationResponse {
  package: any
}

export type AgentToolApproval = 'inherit' | 'allow' | 'ask' | 'deny'
export type AgentToolPolicyMode = 'strict' | 'allow_below_high' | 'allow_all' | 'custom'

export interface AgentToolSettingView {
  tool_id: string
  name: string
  description: string
  base_description: string
  description_overridden: boolean
  source: string
  risk_level: 'low' | 'medium' | 'high'
  permission_scope: string
  permission_tags: string[]
  max_model_chars: number
  max_model_chars_overridden: boolean
  base_concurrent: boolean
  concurrent: boolean
  concurrent_overridden: boolean
}

export interface AgentToolSettingsView {
  policy: {
    mode: AgentToolPolicyMode
    low?: string
    medium?: string
    high?: string
    tool_overrides: Record<string, { approval?: AgentToolApproval; risk_level?: string | null }>
  }
  default_max_model_chars: number
  tools: AgentToolSettingView[]
}

interface AgentToolSettingsResponse {
  tool_settings: AgentToolSettingsView
}

export interface AgentPackageResourceDescriptorView {
  resource_id: string
  description: string
  required: boolean
  configured: boolean
  value?: unknown
  secret_fields: string[]
  used_by: string[]
  sandbox_access_expectation: string
  value_schema: Record<string, unknown>
  key_available: boolean
}

export interface AgentPackageResourcesResponse {
  package_id: string
  key_available: boolean
  resources: AgentPackageResourceDescriptorView[]
  migration: { status: string; migrated?: boolean; reason?: string }
}

export const agentPackagesApi = {
  list: () => requestEvent('/api/agent-packages'),
  select: (packageId: string, purpose?: 'run' | 'evolution') =>
    requestEvent('/api/agent-packages/select', {
      method: 'POST',
      body: JSON.stringify({ package_id: packageId, purpose }),
    }),
  instances: () => requestEvent('/api/agent-packages/instances'),
  recentSessions: (limit = 5) =>
    requestJson<RecentAgentSessionsResponse>(withQuery('/api/agent-packages/recent-sessions', { limit })),
  initialize: (packageId: string) =>
    requestEvent(`/api/agent-packages/${encodeURIComponent(packageId)}/initialize`, { method: 'POST' }),
  shutdown: (packageId: string) =>
    requestEvent(`/api/agent-packages/${encodeURIComponent(packageId)}/shutdown`, { method: 'POST' }),
  delete: (packageId: string) =>
    requestEvent(`/api/agent-packages/${encodeURIComponent(packageId)}`, { method: 'DELETE' }),
  exportArchive: (packageId: string) =>
    requestBlob(`/api/agent-packages/${encodeURIComponent(packageId)}/export`),
  toolSettings: (packageId: string) =>
    requestJson<AgentToolSettingsResponse>(
      `/api/agent-packages/${encodeURIComponent(packageId)}/tool-settings`,
    ),
  updateToolPolicy: (packageId: string, mode: AgentToolPolicyMode) =>
    requestJson<AgentToolSettingsResponse>(
      `/api/agent-packages/${encodeURIComponent(packageId)}/tool-settings/policy`,
      {
        method: 'PATCH',
        body: JSON.stringify({ policy: { mode } }),
      },
    ),
  updateToolSettings: (
    packageId: string,
    toolId: string,
    payload: {
      description: string
      max_model_chars: number
      approval: AgentToolApproval
      concurrent: boolean
    },
  ) =>
    requestJson<AgentToolSettingsResponse>(
      `/api/agent-packages/${encodeURIComponent(packageId)}/tool-settings/${encodeURIComponent(toolId)}`,
      {
        method: 'PATCH',
        body: JSON.stringify(payload),
      },
    ),
  resetToolSettings: (packageId: string, toolId: string) =>
    requestJson<AgentToolSettingsResponse>(
      `/api/agent-packages/${encodeURIComponent(packageId)}/tool-settings/${encodeURIComponent(toolId)}`,
      { method: 'DELETE' },
    ),
  updateContextConfig: (packageId: string, config: Record<string, unknown>) =>
    requestJson<AgentPackageConfigurationResponse>(
      `/api/agent-packages/${encodeURIComponent(packageId)}/context-config`,
      {
        method: 'PATCH',
        body: JSON.stringify({ config }),
      },
    ),
  updateSchedulerConfig: (packageId: string, config: Record<string, unknown>) =>
    requestJson<AgentPackageConfigurationResponse>(
      `/api/agent-packages/${encodeURIComponent(packageId)}/scheduler-config`,
      {
        method: 'PATCH',
        body: JSON.stringify({ config }),
      },
    ),
  updateModelOverrides: (
    packageId: string,
    bindings: Record<string, { temperature: number | null; max_output_tokens: number | null }>,
    toolBindings: Record<string, { temperature: number | null; max_output_tokens: number | null }>,
  ) =>
    requestJson<AgentPackageConfigurationResponse>(
      `/api/agent-packages/${encodeURIComponent(packageId)}/model-overrides`,
      {
        method: 'PATCH',
        body: JSON.stringify({ bindings, tool_bindings: toolBindings }),
      },
    ),
  resources: (packageId: string) =>
    requestJson<AgentPackageResourcesResponse>(`/api/agent-packages/${encodeURIComponent(packageId)}/resources`),
  putResource: (packageId: string, resourceId: string, value: unknown) =>
    requestJson(`/api/agent-packages/${encodeURIComponent(packageId)}/resources/${encodeURIComponent(resourceId)}`, {
      method: 'PUT',
      body: JSON.stringify({ value }),
    }),
  deleteResource: (packageId: string, resourceId: string) =>
    requestJson(`/api/agent-packages/${encodeURIComponent(packageId)}/resources/${encodeURIComponent(resourceId)}`, {
      method: 'DELETE',
    }),
  sessions: (packageId: string) => requestEvent(`/api/agent-packages/${encodeURIComponent(packageId)}/sessions`),
  session: (packageId: string, sessionId: string) =>
    requestEvent(
      `/api/agent-packages/${encodeURIComponent(packageId)}/sessions/${encodeURIComponent(sessionId)}`
    ),
  deleteSession: (packageId: string, sessionId: string) =>
    requestEvent(
      `/api/agent-packages/${encodeURIComponent(packageId)}/sessions/${encodeURIComponent(sessionId)}`,
      { method: 'DELETE' }
    ),
}
