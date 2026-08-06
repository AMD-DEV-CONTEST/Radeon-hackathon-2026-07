/**
 * 协议类型定义
 * 与后端 FactoryFrontendEvent/Command 协议对应
 */

// ========== 基础类型 ==========

export type FactoryMode = 'create_agent' | 'evolve_agent' | 'agent_package' | 'agent_group'

export type RunStatus = 'idle' | 'running' | 'stopping' | 'waiting_for_workers' | 'interrupted' | 'completed' | 'stopped' | 'cancelled' | 'failed'

export type PlanStepStatus = 'pending' | 'in_progress' | 'completed' | 'failed' | 'skipped'

export type WorkspaceScope = 'package' | 'runtime' | 'workdir' | 'artifacts' | 'extensions'

export type RuntimeAttachmentKind = 'file' | 'text' | 'url'

export interface RuntimeAttachmentInput {
  kind: RuntimeAttachmentKind
  name: string
  content?: string
  encoding?: 'base64'
  source_kind?: string
  mime_type?: string
}

export type ContextReferenceKind = 'message_reference' | 'workspace_file' | 'text_selection'

export interface ContextReferenceInput extends RuntimeAttachmentInput {
  kind: 'text' | 'file'
  source_kind: ContextReferenceKind
}

export interface TranscriptAttachmentView {
  kind: RuntimeAttachmentKind
  name: string
  source_kind?: string
  mime_type?: string
  workspace_scope?: WorkspaceScope
  path?: string
  size_bytes?: number
}

export interface TranscriptReasoningView {
  content: string
  active: boolean
  completedAt: string | null
}

export type ChatMessageRole = 'user' | 'assistant' | 'system'
export type ChatMessageStatus = 'streaming' | 'completed' | 'failed' | 'stopped'
export type ChatMessagePartStatus =
  | 'streaming'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'stopped'
  | 'requested'
  | 'awaiting_approval'
  | 'running'

export interface BaseChatMessagePart {
  id: string
  type: string
  status?: ChatMessagePartStatus
  createdAt?: string
  startedAt?: string | null
  updatedAt?: string
}

export interface TextMessagePart extends BaseChatMessagePart {
  type: 'text'
  format: 'markdown' | 'plain'
  text: string
}

export interface ReasoningMessagePart extends BaseChatMessagePart {
  type: 'reasoning'
  text: string
}

export interface ToolCallMessagePart extends BaseChatMessagePart {
  type: 'tool_call'
  toolName: string
  callId: string | null
  arguments: unknown
  liveOutput?: unknown
  approvalState?: ToolActivity['approvalState']
}

export interface ToolResultMessagePart extends BaseChatMessagePart {
  type: 'tool_result'
  toolName: string
  callId: string | null
  output: unknown
  error?: unknown
}

export interface ToolExecutionMessagePart extends BaseChatMessagePart {
  type: 'tool_execution'
  toolName: string
  callId: string | null
  arguments: unknown
  output: unknown
  error?: unknown
  approvalState?: ToolActivity['approvalState']
  artifacts: ArtifactMessagePart[]
}

export interface ArtifactMessagePart extends BaseChatMessagePart {
  type: 'artifact'
  name: string
  path?: string | null
  mimeType?: string | null
  sizeBytes?: number | null
}

export interface AttachmentMessagePart extends BaseChatMessagePart {
  type: 'attachment'
  attachment: TranscriptAttachmentView
}

export interface ErrorMessagePart extends BaseChatMessagePart {
  type: 'error'
  message: string
  details?: unknown
}

export interface StatusMessagePart extends BaseChatMessagePart {
  type: 'status'
  message: string
}

export type ChatMessagePart =
  | TextMessagePart
  | ReasoningMessagePart
  | ToolCallMessagePart
  | ToolResultMessagePart
  | ToolExecutionMessagePart
  | ArtifactMessagePart
  | AttachmentMessagePart
  | ErrorMessagePart
  | StatusMessagePart

// ========== 命令类型 ==========

export interface FactoryFrontendCommand {
  type: string
  request_id: string | null
  session_id: string | null
  resume_latest: boolean
  mode: FactoryMode | null
  message: string | null
  payload: Record<string, any>
  options: Record<string, any>
}

// ========== 事件类型 ==========

export interface FactoryFrontendEvent {
  event_id: string
  protocol_version: string
  event_type: string
  persistence?: 'durable' | 'transient'
  producer_type: string
  request_id: string | null
  run_id: string | null
  session_id: string | null
  thread_id: string | null
  mode: FactoryMode | null
  graph_id: string | null
  node_id: string | null
  node_label: string | null
  node_kind: string | null
  stage_id: string | null
  span_id: string | null
  parent_span_id: string | null
  sequence: number
  timestamp: string
  severity: string | null
  message: string | null
  payload: Record<string, any>
  process_event?: boolean
}

export interface RuntimeOptionsView {
  show_state?: boolean
  show_messages?: boolean
  context_window_tokens: number | null
  context_window_tokens_source: 'model_profile' | 'unset' | string
}

// ========== 对话相关 ==========

export interface ChatMessage {
  id: string
  role: ChatMessageRole
  parts: ChatMessagePart[]
  status?: ChatMessageStatus
  // Derived fields for summaries, interruption payloads, and compact side-channel output.
  // Rendering and persistence use parts as the source of truth.
  content: string
  timestamp: string
  streamId?: string
  attachments?: TranscriptAttachmentView[]
  reasoning?: TranscriptReasoningView
  metadata?: any
}

export type TranscriptItem = ChatMessage

export interface ConversationTurn {
  id: string
  requestId: string | null
  status: RunStatus
  userMessage: TranscriptItem | null
  assistantMessages: TranscriptItem[]
  tools: ToolActivity[]
  startedAt: string
  completedAt: string | null
  errorMessage: string | null
  metadata?: Record<string, any>
}

export interface ConversationScopeState {
  transcript: TranscriptItem[]
  conversationTurns: ConversationTurn[]
  timeline: TimelineItem[]
  tools: ToolActivity[]
  currentPlan: RuntimePlanView | null
  contextActivity: RuntimeActivityView
  contextWindow: ContextWindowView | null
  memoryActivity: RuntimeActivityView
  modelStreams: Record<string, ModelStream>
  activeFactorySessionId: string | null
  activeAgentSessionId: string | null
  activeWorkspaceId: string | null
  activeRequestId?: string | null
  runStatus?: RunStatus
  pendingInterrupt?: FactoryFrontendEvent | null
  createAgentPublishReady?: Record<string, any> | null
  currentRunId?: string | null
  nodes?: Record<string, NodeViewState>
  stages?: Record<string, StageStatus>
}

export interface AgentPackageSelectionIntent {
  packageId: string | null
  purpose: 'run' | 'evolution' | null
}

// ========== 模型流 ==========

export interface ModelStream {
  streamId: string
  requestId?: string | null
  nodeId: string | null
  content: string
  reasoningContent: string
  reasoningActive: boolean
  reasoningCompletedAt: string | null
  active: boolean
  completedAt: string | null
  visibleToUser: boolean
}

export interface ActiveRequestView {
  requestId: string
  status: RunStatus
  mode: FactoryMode | null
  runId: string | null
  conversationScope?: string | null
  background: boolean
  source: 'user' | 'internal' | 'scheduler'
  startedAt: string
  completedAt: string | null
  payload: Record<string, any>
}

export interface QueuedMessageView {
  requestId: string
  content: string
  position: number
  steering: boolean
}

// ========== 节点和阶段 ==========

export interface NodeViewState {
  nodeId: string
  stageId: string | null
  status: 'pending' | 'running' | 'completed' | 'failed'
  label: string | null
  kind: string | null
  startedAt: string
  completedAt: string | null
  failedAt: string | null
  message: string | null
  payload: Record<string, any>
}

export interface StageStatus {
  stageId: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  nodeId: string | null
  startedAt: string
  completedAt: string | null
  failedAt: string | null
  lastEventType: string
  lastMessage: string | null
}

// ========== 工具活动 ==========

export interface ToolActivity {
  activityKey: string
  requestId?: string | null
  eventType: string
  timestamp: string
  createdAt: string
  startedAt?: string | null
  stageId: string | null
  nodeId: string | null
  toolCallId: string | null
  toolName: string
  status: 'proposed' | 'approval' | 'started' | 'completed' | 'failed' | 'cancelled' | 'observed'
  approvalState: 'pending' | 'approved' | 'denied' | 'rejected' | null
  payload: Record<string, any>
}

// ========== 计划 ==========

export interface RuntimePlanView {
  version?: string
  goal: string
  status: string
  current_step_id?: string | null
  steps: PlanStep[]
  source_node_id?: string | null
  updatedAt?: string
}

export interface PlanStep {
  step_id: string
  title: string
  objective: string | null
  status: PlanStepStatus
  result_summary: string | null
}

// ========== Timeline ==========

export interface TimelineItem {
  id: string
  eventType: string
  timestamp: string
  spanId: string | null
  parentSpanId: string | null
  stageId: string | null
  nodeId: string | null
  nodeLabel: string | null
  message: string | null
  severity: string | null
  payload: Record<string, any>
}

// ========== 工作区 ==========

export interface WorkspaceRootView {
  scope: WorkspaceScope
  name?: string
  path?: string
  exists: boolean
}

export interface WorkspaceEntry {
  scope?: WorkspaceScope
  path: string
  name: string
  kind: 'file' | 'directory'
  sizeBytes: number | null
  updatedAt: string | null
  mount: boolean
  mountId: string | null
  mountSource: string | null
  connected: boolean | null
}

export interface WorkspaceMountView {
  mountId: string
  name: string
  sourcePath: string
  createdAt: string
  connected: boolean
}

export interface WorkspaceFileView {
  name: string
  scope?: WorkspaceScope
  path?: string
  kind: 'text' | 'binary'
  mimeType: string | null
  encoding: 'utf-8' | 'base64' | string
  content: string
  contentBase64: string
  sizeBytes: number
  truncated: boolean
  payload?: Record<string, any>
}

// ========== 知识库 ==========

export interface KnowledgeSourceView {
  name: string
  status: string
  documentCount: number | null
  mode: string | null
  updatedAt?: string
  payload: Record<string, any>
}

export interface KnowledgeDocumentView {
  documentId?: string
  name?: string
  kind?: string
  title?: string
  sourceName?: string | null
  documentType?: string | null
  uri?: string | null
  payload: Record<string, any>
}

export interface KnowledgeSearchResultView {
  documentId?: string
  score: number | null
  preview?: string
  title?: string
  content?: string
  payload: Record<string, any>
}

// ========== 定时任务 ==========

export interface SchedulerJobView {
  title: string
  status: string
  enabled: boolean
  schedule: string
  targetType: string | null
  targetLabel?: string
  payload: Record<string, any>
}

export interface SchedulerToolOptionView {
  id: string
  name: string
  description?: string
  riskLevel?: string
  inputSchema?: Record<string, any>
}

export interface SchedulerRunNoticeView {
  id: string
  jobId: string | null
  runId: string | null
  requestId: string | null
  status: string
  title: string
  summary: string
  targetType: string | null
  targetScope: string | null
  packageId: string | null
  packageName: string | null
  sessionId: string | null
  factorySessionId: string | null
  reportPath: string | null
  timestamp: string
  unread: boolean
  conversationScope: string | null
  payload: Record<string, any>
}

// ========== 扩展 ==========

export interface ExtensionItemView {
  name?: string
  kind: 'mcp' | 'skill'
  scope?: string
  status?: string
  enabled: boolean
  payload: Record<string, any>
}

export type ToolPermissionMode = 'strict' | 'allow_below_high' | 'allow_all' | 'custom'
export type ToolRiskLevel = 'low' | 'medium' | 'high'
export type ToolPermissionApproval = 'inherit' | 'allow' | 'ask' | 'deny'

export interface ToolPermissionOverrideView {
  risk_level?: ToolRiskLevel | null
  approval?: ToolPermissionApproval
}

export interface ToolPermissionPolicyView {
  mode: ToolPermissionMode
  low?: string
  medium?: string
  high?: string
  tool_overrides: Record<string, ToolPermissionOverrideView>
}

export interface ToolPermissionItemView {
  tool_id: string
  name: string
  description: string
  source: string
  risk_level: ToolRiskLevel
  permission_scope: string
  permission_tags: string[]
}

export interface ToolPermissionsView {
  policy: ToolPermissionPolicyView
  tools: ToolPermissionItemView[]
}

export interface RuntimeActivityView {
  status: string
  eventType?: string
  payload?: Record<string, any>
}

export interface ContextWindowView {
  tokenCount: number | null
  contextWindowTokens: number | null
  compressionThresholdTokens: number | null
  tokenCountMethod: string | null
  source: string | null
  modelRole: string | null
  nodeId: string | null
  updatedAt: string
  payload: Record<string, any>
}

export interface RuntimeViewState {
  protocolVersion: string
  connectionStatus: 'disconnected' | 'connecting' | 'connected' | 'error' | 'reconnecting'
  runtimeOptions: RuntimeOptionsView
  activeRequestId: string | null
  activeRequests: Record<string, ActiveRequestView>
  runStatus: RunStatus
  pendingInterrupt: FactoryFrontendEvent | null
  createAgentPublishReady: Record<string, any> | null
  currentMode: FactoryMode | null
  activeFactorySessionId: string | null
  activeAgentSessionId: string | null
  activeWorkspaceId: string | null
  currentRunId: string | null
  nodes: Record<string, NodeViewState>
  stages: Record<string, StageStatus>
  modelStreams: Record<string, ModelStream>
  tools: ToolActivity[]
  currentPlan: RuntimePlanView | null
  activeConversationScope: string | null
  conversationScopes: Record<string, ConversationScopeState>
  transcript: TranscriptItem[]
  conversationTurns: ConversationTurn[]
  timeline: TimelineItem[]
  debugEvents: FactoryFrontendEvent[]
  contextActivity: RuntimeActivityView
  contextWindow: ContextWindowView | null
  memoryActivity: RuntimeActivityView
  knowledgeActivity: Record<string, any>[]
  schedulerActivity: Record<string, any>[]
  workspaceEntries: WorkspaceEntry[]
  workspaceRoots: WorkspaceRootView[]
  workspaceFile: WorkspaceFileView | null
  knowledgeSources: KnowledgeSourceView[]
  knowledgeDocuments: KnowledgeDocumentView[]
  knowledgeResults: KnowledgeSearchResultView[]
  knowledgeDocument: Record<string, any> | null
  schedulerJobs: SchedulerJobView[]
  schedulerToolOptions: SchedulerToolOptionView[]
  schedulerRunNotices: SchedulerRunNoticeView[]
  extensionItems: ExtensionItemView[]
  extensionTestResult: Record<string, any> | null
  extensionBindings: { mcp_server_ids: string[]; skill_ids: string[] }
  toolPermissions: ToolPermissionsView | null
  sessions: any[]
  agentPackages: any[]
  agentPackageSelectionIntent: AgentPackageSelectionIntent
  selectedAgentPackage: any | null
  agentSessions: any[]
}
