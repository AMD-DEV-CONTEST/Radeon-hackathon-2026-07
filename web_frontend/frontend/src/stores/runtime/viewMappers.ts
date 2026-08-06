import type {
  ContextWindowView,
  ExtensionItemView,
  FactoryFrontendEvent,
  KnowledgeDocumentView,
  KnowledgeSearchResultView,
  KnowledgeSourceView,
  SchedulerJobView,
  SchedulerRunNoticeView,
  SchedulerToolOptionView,
  ToolPermissionApproval,
  ToolPermissionMode,
  ToolPermissionsView,
  ToolRiskLevel,
  WorkspaceEntry,
  WorkspaceFileView,
  WorkspaceRootView,
} from '@/types/protocol'

export function contextWindowView(event: FactoryFrontendEvent): ContextWindowView {
  const payload = event.payload || {}
  return {
    tokenCount: optionalNumber(payload.token_count),
    contextWindowTokens: optionalNumber(payload.context_window_tokens),
    compressionThresholdTokens: optionalNumber(payload.compression_threshold_tokens),
    tokenCountMethod: optionalString(payload.token_count_method),
    source: optionalString(payload.source),
    modelRole: optionalString(payload.model_role),
    nodeId: optionalString(payload.node_id || event.node_id),
    updatedAt: event.timestamp,
    payload,
  }
}

export function workspaceRootView(root: any): WorkspaceRootView {
  return {
    scope: root.scope,
    name: String(root.name || root.scope || 'Workspace'),
    exists: root.exists !== false,
  }
}

export function workspaceEntryView(entry: any): WorkspaceEntry {
  return {
    name: String(entry.name || entry.path || 'file'),
    scope: entry.scope,
    path: String(entry.path || ''),
    kind: entry.kind === 'directory' ? 'directory' : 'file',
    sizeBytes: entry.size_bytes ?? entry.sizeBytes ?? null,
    updatedAt: entry.updated_at || entry.updatedAt || null,
    mount: entry.mount === true,
    mountId: entry.mount_id || entry.mountId || null,
    mountSource: entry.mount_source || entry.mountSource || null,
    connected: typeof entry.connected === 'boolean' ? entry.connected : null,
  }
}

export function workspaceFileView(payload: Record<string, any>): WorkspaceFileView {
  return {
    name: String(payload.name || payload.path || 'file'),
    scope: payload.scope,
    path: String(payload.path || ''),
    kind: payload.kind === 'binary' ? 'binary' : 'text',
    mimeType: payload.mime_type || payload.mimeType || null,
    encoding: String(payload.encoding || (payload.kind === 'binary' ? 'base64' : 'utf-8')),
    sizeBytes: Number(payload.size_bytes || payload.sizeBytes || 0),
    content: String(payload.content || ''),
    contentBase64: String(payload.content_base64 || payload.contentBase64 || ''),
    truncated: Boolean(payload.truncated),
    payload,
  }
}

export function knowledgeSourceView(source: any, timestamp: string): KnowledgeSourceView {
  const name = String(source?.display_name || source?.name || '')
  return {
    name,
    status: String(source?.status || 'updating'),
    mode: source?.mount_mode || source?.mode || null,
    documentCount: source?.document_count ?? source?.estimated_documents ?? source?.counts?.documents_loaded ?? null,
    updatedAt: source?.updated_at || timestamp,
    payload: source || {},
  }
}

export function knowledgeDocumentView(document: any): KnowledgeDocumentView {
  return {
    documentId: document.document_id || document.documentId || undefined,
    title: String(document.title || document.uri || ''),
    sourceName: document.source_name || null,
    documentType: document.document_type || null,
    uri: document.uri || null,
    payload: document || {},
  }
}

export function knowledgeSearchResultView(result: any): KnowledgeSearchResultView {
  return {
    title: String(result.title || ''),
    content: String(result.content || ''),
    score: typeof result.score === 'number' ? result.score : null,
    payload: result || {},
  }
}

export function schedulerJobView(job: any): SchedulerJobView {
  const target = job.target || {}
  const targetPayload = target.payload || {}
  const targetType = target.target_type || null
  return {
    title: String(job.task_content || job.title || ''),
    schedule: String(job.schedule_expr || ''),
    enabled: job.enabled !== false,
    status: job.enabled === false ? 'paused' : 'enabled',
    targetType,
    targetLabel: schedulerJobTargetLabel(targetType, targetPayload),
    payload: job || {},
  }
}

export function schedulerToolOptionView(tool: any): SchedulerToolOptionView | null {
  const id = String(tool.id || '')
  if (!id) return null
  return {
    id,
    name: String(tool.name || tool.id || ''),
    description: tool.description ? String(tool.description) : undefined,
    riskLevel: tool.risk_level ? String(tool.risk_level) : undefined,
    inputSchema: tool.input_schema && typeof tool.input_schema === 'object' ? tool.input_schema : undefined,
  }
}

export function schedulerRunNoticeView(event: FactoryFrontendEvent): SchedulerRunNoticeView | null {
  const payload = event.payload || {}
  const nested = payload.payload && typeof payload.payload === 'object' ? payload.payload : {}
  const execution = nested.execution && typeof nested.execution === 'object' ? nested.execution : {}
  const runId = String(payload.run_id || execution.run_id || nested.run_id || '')
  const jobId = payload.job_id ? String(payload.job_id) : null
  const requestId = String(nested.request_id || execution.request_id || event.request_id || (runId ? `scheduler-${runId}` : ''))
  const status = String(payload.status || execution.status || '').trim() || event.event_type.replace('scheduler_run_', '')
  const targetType = payload.target_type ? String(payload.target_type) : null
  const targetScope = execution.target_scope ? String(execution.target_scope) : null
  const conversation = execution.conversation && typeof execution.conversation === 'object' ? execution.conversation : {}
  const agentSession = execution.agent_session && typeof execution.agent_session === 'object' ? execution.agent_session : {}
  const sessionId = String(conversation.session_id || agentSession.session_id || '').trim() || null
  const factorySessionId = null
  const packageId = String(payload.package_id || execution.package_id || '').trim() || null
  const packageName = String(payload.package_name || execution.package_name || '').trim() || null
  const title = String(payload.task_content || '').trim()
    || schedulerNoticeTitle(packageName, targetScope, targetType, packageId)
  const summary = String(
    payload.summary ||
    execution.output_summary ||
    execution.error_summary ||
    execution.error ||
    payload.error_summary ||
    schedulerStatusText(status)
  )
  if (!runId && !requestId) return null
  return {
    id: runId || requestId,
    jobId,
    runId: runId || null,
    requestId: requestId || null,
    status,
    title,
    summary,
    targetType,
    targetScope,
    packageId,
    packageName,
    sessionId,
    factorySessionId,
    reportPath: payload.report_path ? String(payload.report_path) : null,
    timestamp: event.timestamp,
    unread: !['scheduled', 'running', 'pending'].includes(status),
    conversationScope: null,
    payload,
  }
}

export function extensionItemView(item: any, fallbackKind: 'mcp' | 'skill'): ExtensionItemView {
  const kind = item.kind === 'skill' ? 'skill' : item.kind === 'mcp' ? 'mcp' : fallbackKind
  return {
    name: String(item.name || (kind === 'mcp' ? 'MCP' : 'Skill')),
    kind,
    scope: String(item.scope || 'local'),
    status: String(item.status || (item.enabled === false ? 'disabled' : 'enabled')),
    enabled: item.enabled !== false,
    payload: item.payload || item || {},
  }
}

export function toolPermissionsView(payload: any): ToolPermissionsView | null {
  if (!payload || typeof payload !== 'object') return null
  const policy = payload.policy && typeof payload.policy === 'object' ? payload.policy : {}
  const tools = Array.isArray(payload.tools) ? payload.tools : []
  return {
    policy: {
      mode: toolPermissionMode(policy.mode),
      low: typeof policy.low === 'string' ? policy.low : undefined,
      medium: typeof policy.medium === 'string' ? policy.medium : undefined,
      high: typeof policy.high === 'string' ? policy.high : undefined,
      tool_overrides: toolPermissionOverrides(policy.tool_overrides),
    },
    tools: tools.map(toolPermissionItemView).filter(Boolean) as ToolPermissionsView['tools'],
  }
}

function toolPermissionItemView(item: any) {
  const toolId = String(item?.tool_id || '').trim()
  if (!toolId) return null
  return {
    tool_id: toolId,
    name: String(item.name || toolId),
    description: String(item.description || ''),
    source: String(item.source || 'package'),
    risk_level: toolRiskLevel(item.risk_level),
    permission_scope: String(item.permission_scope || ''),
    permission_tags: Array.isArray(item.permission_tags) ? item.permission_tags.map(String) : [],
  }
}

function toolPermissionOverrides(payload: any): ToolPermissionsView['policy']['tool_overrides'] {
  if (!payload || typeof payload !== 'object') return {}
  const overrides: ToolPermissionsView['policy']['tool_overrides'] = {}
  Object.entries(payload).forEach(([toolId, value]) => {
    if (!value || typeof value !== 'object') return
    const item = value as Record<string, any>
    overrides[toolId] = {
      risk_level: item.risk_level ? toolRiskLevel(item.risk_level) : null,
      approval: toolPermissionApproval(item.approval),
    }
  })
  return overrides
}

function toolPermissionMode(value: unknown): ToolPermissionMode {
  return value === 'strict' || value === 'allow_all' || value === 'custom'
    ? value
    : 'allow_below_high'
}

function toolRiskLevel(value: unknown): ToolRiskLevel {
  return value === 'medium' || value === 'high' ? value : 'low'
}

function toolPermissionApproval(value: unknown): ToolPermissionApproval {
  return value === 'allow' || value === 'ask' || value === 'deny' ? value : 'inherit'
}

function schedulerJobTargetLabel(targetType: string | null, payload: Record<string, any>): string {
  if (targetType === 'tool_call') return String(payload.tool_id || '')
  return targetType || ''
}

function schedulerNoticeTitle(
  packageName: string | null,
  targetScope: string | null,
  targetType: string | null,
  packageId: string | null,
): string {
  if (targetScope === 'agent_package' || packageId) return packageName || 'agent_package'
  return targetType || 'chat'
}

function schedulerStatusText(status: string): string {
  return status || 'updated'
}

function optionalNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : null
  }
  return null
}

function optionalString(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const trimmed = value.trim()
  return trimmed ? trimmed : null
}
