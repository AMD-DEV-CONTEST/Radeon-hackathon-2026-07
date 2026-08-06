import type {
  ConversationTurn,
  FactoryFrontendEvent,
  RuntimeViewState,
  ToolActivity,
  TranscriptItem,
} from '@/types/protocol'
import {
  toolArtifactParts,
  toolCallPart,
  toolResultPart,
  upsertPart,
} from './messageParts'
import { toolPayloadArguments, toolPayloadValue } from './toolPayload'

type ConversationMutationState = Pick<
  RuntimeViewState,
  | 'activeRequestId'
  | 'conversationTurns'
  | 'runStatus'
  | 'tools'
  | 'transcript'
>

export function ensureConversationTurn(
  state: ConversationMutationState,
  requestId: string | null,
  timestamp?: string,
): ConversationTurn {
  const existing = requestId
    ? state.conversationTurns.find((turn) => turn.requestId === requestId)
    : null
  if (existing) return existing

  const fallback = !requestId ? state.conversationTurns[state.conversationTurns.length - 1] : null
  if (fallback && fallback.status === 'running') return fallback

  const turn: ConversationTurn = {
    id: requestId || `turn-${Date.now()}`,
    requestId,
    status: state.runStatus,
    userMessage: null,
    assistantMessages: [],
    tools: [],
    startedAt: timestamp || new Date().toISOString(),
    completedAt: null,
    errorMessage: null,
  }
  state.conversationTurns.push(turn)
  return turn
}

export function upsertToolActivityFromEvent(
  state: ConversationMutationState,
  event: FactoryFrontendEvent,
  status: ToolActivity['status'],
): ToolActivity | null {
  const payload = event.payload || {}
  const toolCallId = toolPayloadValue(payload, ['tool_call_id', 'toolCallId'])
  const toolName = toolPayloadValue(payload, ['tool_name', 'tool_id', 'name'])
  const activityKey = String(toolCallId || event.span_id || event.event_id)
  const existingIndex = state.tools.findIndex((item) => (
    item.activityKey === activityKey ||
    Boolean(toolCallId && item.toolCallId === String(toolCallId))
  ))
  const existing = existingIndex >= 0 ? state.tools[existingIndex] : null
  const activity: ToolActivity = {
    activityKey: existing?.activityKey || activityKey,
    requestId: event.request_id || existing?.requestId || null,
    eventType: event.event_type,
    timestamp: event.timestamp,
    createdAt: existing?.createdAt || event.timestamp,
    startedAt: existing?.startedAt || (status === 'started' ? event.timestamp : null),
    stageId: event.stage_id || existing?.stageId || null,
    nodeId: event.node_id || existing?.nodeId || null,
    toolCallId: toolCallId ? String(toolCallId) : existing?.toolCallId || null,
    toolName: toolName ? String(toolName) : existing?.toolName || 'tool_call',
    status,
    approvalState: existing?.approvalState || null,
    payload: {
      ...(existing?.payload || {}),
      ...payload,
      arguments: {
        ...toolPayloadArguments(existing?.payload || {}),
        ...toolPayloadArguments(payload),
      },
    },
  }

  if (existingIndex >= 0) {
    state.tools[existingIndex] = activity
  } else {
    state.tools.push(activity)
  }
  upsertTurnTool(state, activity)
  upsertToolMessagePart(state, activity)
  return activity
}

export function upsertToolMessagePart(
  state: ConversationMutationState,
  activity: ToolActivity,
) {
  const messageId = `tool-${activity.activityKey}`
  const existingIndex = state.transcript.findIndex((item) => item.id === messageId)
  const resultPart = toolResultPart(activity)
  const parts = [
    toolCallPart(activity),
    ...(resultPart ? [resultPart] : []),
    ...toolArtifactParts(activity),
  ]
  const status = activity.status === 'failed'
    ? 'failed'
    : ['completed', 'cancelled', 'observed'].includes(activity.status)
      ? 'completed'
      : 'streaming'

  if (existingIndex >= 0) {
    const item = state.transcript[existingIndex]
    let nextParts = item.parts
    for (const part of parts) {
      nextParts = upsertPart(nextParts, part)
    }
    item.parts = nextParts
    item.timestamp = activity.timestamp
    item.status = status
    item.content = ''
    syncTurnAssistantMessage(state, item, activity)
    return
  }

  const item: TranscriptItem = {
    id: messageId,
    role: 'assistant',
    content: '',
    timestamp: activity.createdAt || activity.timestamp,
    status,
    parts,
    metadata: {
      tool_activity: true,
      request_id: activity.requestId,
      tool_call_id: activity.toolCallId,
      tool_name: activity.toolName,
    },
  }
  state.transcript.push(item)
  syncTurnAssistantMessage(state, item, activity)
}

function syncTurnAssistantMessage(
  state: ConversationMutationState,
  message: TranscriptItem,
  activity: ToolActivity,
) {
  const turn = ensureConversationTurn(state, activity.requestId || state.activeRequestId, activity.timestamp)
  const existingIndex = turn.assistantMessages.findIndex((item) => item.id === message.id)
  if (existingIndex >= 0) {
    turn.assistantMessages[existingIndex] = message
    return
  }
  turn.assistantMessages.push(message)
}

export function upsertTurnTool(
  state: ConversationMutationState,
  tool: ToolActivity,
) {
  const turn = ensureConversationTurn(state, tool.requestId || state.activeRequestId, tool.timestamp)
  const index = turn.tools.findIndex((item) => item.activityKey === tool.activityKey)
  if (index >= 0) {
    turn.tools[index] = { ...tool }
  } else {
    turn.tools.push({ ...tool })
  }
}
