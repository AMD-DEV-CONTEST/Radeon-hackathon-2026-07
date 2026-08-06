import type { ConversationScopeState, RuntimeViewState } from '@/types/protocol'

type ConversationScopeSource = Pick<
  RuntimeViewState,
  | 'transcript'
  | 'conversationTurns'
  | 'timeline'
  | 'tools'
  | 'currentPlan'
  | 'contextActivity'
  | 'contextWindow'
  | 'memoryActivity'
  | 'modelStreams'
  | 'activeFactorySessionId'
  | 'activeAgentSessionId'
  | 'activeWorkspaceId'
  | 'activeRequestId'
  | 'runStatus'
  | 'pendingInterrupt'
  | 'createAgentPublishReady'
  | 'currentRunId'
  | 'nodes'
  | 'stages'
>

export function buildConversationScopeState(source: ConversationScopeSource): ConversationScopeState {
  return {
    transcript: source.transcript.map(cloneTranscriptItem),
    conversationTurns: source.conversationTurns.map((turn) => ({
      ...turn,
      userMessage: turn.userMessage ? cloneTranscriptItem(turn.userMessage) : null,
      assistantMessages: turn.assistantMessages.map(cloneTranscriptItem),
      tools: turn.tools.map((tool) => ({ ...tool, payload: { ...(tool.payload || {}) } })),
      metadata: { ...(turn.metadata || {}) },
    })),
    timeline: source.timeline.map((item) => ({ ...item, payload: { ...(item.payload || {}) } })),
    tools: source.tools.map((tool) => ({ ...tool, payload: { ...(tool.payload || {}) } })),
    currentPlan: source.currentPlan
      ? { ...source.currentPlan, steps: source.currentPlan.steps.map((step) => ({ ...step })) }
      : null,
    contextActivity: {
      ...source.contextActivity,
      payload: { ...(source.contextActivity.payload || {}) },
    },
    contextWindow: source.contextWindow
      ? { ...source.contextWindow, payload: { ...(source.contextWindow.payload || {}) } }
      : null,
    memoryActivity: {
      ...source.memoryActivity,
      payload: { ...(source.memoryActivity.payload || {}) },
    },
    modelStreams: Object.fromEntries(
      Object.entries(source.modelStreams).map(([key, stream]) => [key, { ...stream }]),
    ),
    activeFactorySessionId: source.activeFactorySessionId,
    activeAgentSessionId: source.activeAgentSessionId,
    activeWorkspaceId: source.activeWorkspaceId,
    activeRequestId: source.activeRequestId,
    runStatus: source.runStatus,
    pendingInterrupt: source.pendingInterrupt
      ? { ...source.pendingInterrupt, payload: { ...(source.pendingInterrupt.payload || {}) } }
      : null,
    createAgentPublishReady: source.createAgentPublishReady ? { ...source.createAgentPublishReady } : null,
    currentRunId: source.currentRunId,
    nodes: Object.fromEntries(
      Object.entries(source.nodes).map(([key, node]) => [key, { ...node, payload: { ...(node.payload || {}) } }]),
    ),
    stages: Object.fromEntries(
      Object.entries(source.stages).map(([key, stage]) => [key, { ...stage }]),
    ),
  }
}

export function normalizeConversationScopeState(saved: ConversationScopeState): ConversationScopeState {
  return {
    transcript: saved.transcript.map(cloneTranscriptItem),
    conversationTurns: saved.conversationTurns.map((turn) => ({
      ...turn,
      userMessage: turn.userMessage ? cloneTranscriptItem(turn.userMessage) : null,
      assistantMessages: turn.assistantMessages.map(cloneTranscriptItem),
      tools: turn.tools.map((tool) => ({ ...tool, payload: { ...(tool.payload || {}) } })),
      metadata: { ...(turn.metadata || {}) },
    })),
    timeline: saved.timeline.map((item) => ({ ...item, payload: { ...(item.payload || {}) } })),
    tools: saved.tools.map((tool) => ({ ...tool, payload: { ...(tool.payload || {}) } })),
    currentPlan: saved.currentPlan
      ? { ...saved.currentPlan, steps: saved.currentPlan.steps.map((step) => ({ ...step })) }
      : null,
    contextActivity: saved.contextActivity
      ? { ...saved.contextActivity, payload: { ...(saved.contextActivity.payload || {}) } }
      : { status: 'idle' },
    contextWindow: saved.contextWindow
      ? { ...saved.contextWindow, payload: { ...(saved.contextWindow.payload || {}) } }
      : null,
    memoryActivity: saved.memoryActivity
      ? { ...saved.memoryActivity, payload: { ...(saved.memoryActivity.payload || {}) } }
      : { status: 'idle' },
    modelStreams: Object.fromEntries(
      Object.entries(saved.modelStreams).map(([key, stream]) => [key, {
        ...stream,
        reasoningContent: stream.reasoningContent || '',
        reasoningActive: Boolean(stream.reasoningActive),
        reasoningCompletedAt: stream.reasoningCompletedAt || null,
      }]),
    ),
    activeFactorySessionId: saved.activeFactorySessionId ?? null,
    activeAgentSessionId: saved.activeAgentSessionId,
    activeWorkspaceId: saved.activeWorkspaceId ?? null,
    activeRequestId: saved.activeRequestId ?? null,
    runStatus: saved.runStatus ?? 'idle',
    pendingInterrupt: saved.pendingInterrupt
      ? { ...saved.pendingInterrupt, payload: { ...(saved.pendingInterrupt.payload || {}) } }
      : null,
    createAgentPublishReady: saved.createAgentPublishReady ? { ...saved.createAgentPublishReady } : null,
    currentRunId: saved.currentRunId ?? null,
    nodes: Object.fromEntries(
      Object.entries(saved.nodes || {}).map(([key, node]) => [key, { ...node, payload: { ...(node.payload || {}) } }]),
    ),
    stages: Object.fromEntries(
      Object.entries(saved.stages || {}).map(([key, stage]) => [key, { ...stage }]),
    ),
  }
}

function cloneTranscriptItem<T extends { reasoning?: any; parts?: any[]; attachments?: any[] }>(item: T): T {
  return {
    ...item,
    parts: Array.isArray(item.parts) ? item.parts.map((part) => ({ ...part })) : [],
    attachments: Array.isArray(item.attachments) ? item.attachments.map((attachment) => ({ ...attachment })) : undefined,
    reasoning: item.reasoning ? { ...item.reasoning } : undefined,
  }
}
