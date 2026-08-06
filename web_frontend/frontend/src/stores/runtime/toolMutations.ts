import type { FactoryFrontendEvent, RuntimeViewState, ToolActivity } from '@/types/protocol'
import {
  upsertToolActivityFromEvent,
  upsertToolMessagePart,
  upsertTurnTool,
} from './conversationMutations'
import { isBackgroundEvent } from './eventUtils'
import { toolPayloadValue } from './toolPayload'

type ToolMutationState = Pick<
  RuntimeViewState,
  | 'activeRequestId'
  | 'conversationTurns'
  | 'modelStreams'
  | 'pendingInterrupt'
  | 'runStatus'
  | 'tools'
  | 'transcript'
>

export function applyToolLifecycleEvent(
  state: ToolMutationState,
  event: FactoryFrontendEvent,
  status: ToolActivity['status'],
) {
  if (isBackgroundEvent(event, state.activeRequestId)) return
  const toolCallId = toolPayloadValue(event.payload || {}, ['tool_call_id', 'toolCallId'])
  const existing = state.tools.find((tool) => toolCallId && tool.toolCallId === String(toolCallId))
  const nextStatus = status === 'failed' && (
    toolEventWasUserCancelled(event)
    || existing?.status === 'cancelled'
  )
    ? 'cancelled'
    : status
  upsertToolActivityFromEvent(state, event, nextStatus)
}

export function applyToolApprovalRequested(state: ToolMutationState, event: FactoryFrontendEvent) {
  state.runStatus = 'interrupted'
  state.pendingInterrupt = event

  const requests = event.payload?.requests || []
  requests.forEach((req: any) => {
    const approvalEvent = {
      ...event,
      payload: { ...(event.payload || {}), ...req },
    } satisfies FactoryFrontendEvent
    const activity = upsertToolActivityFromEvent(state, approvalEvent, 'approval')
    if (activity) {
      activity.approvalState = 'pending'
      upsertTurnTool(state, activity)
    }
  })
}

export function applyToolApprovalResolved(state: ToolMutationState, event: FactoryFrontendEvent) {
  if (isBackgroundEvent(event, state.activeRequestId)) return
  const approved = event.payload?.approved
  const toolCallIds = approvalToolCallIds(event.payload)
  state.pendingInterrupt = null
  if (state.runStatus === 'interrupted') {
    state.runStatus = 'running'
  }

  if (toolCallIds.length > 0) {
    const matched = state.tools.filter((item) => item.toolCallId && toolCallIds.includes(item.toolCallId))
    if (matched.length > 0) {
      matched.forEach((tool) => resolveApprovalTool(tool, event, Boolean(approved)))
      matched.forEach((tool) => upsertTurnTool(state, tool))
      matched.forEach((tool) => upsertToolMessagePart(state, tool))
      return
    }
  }

  const pendingTools = state.tools.filter((tool) => tool.status === 'approval' && tool.approvalState === 'pending')
  if (pendingTools.length > 0) {
    pendingTools.forEach((tool) => resolveApprovalTool(tool, event, Boolean(approved)))
    pendingTools.forEach((tool) => upsertTurnTool(state, tool))
    pendingTools.forEach((tool) => upsertToolMessagePart(state, tool))
    return
  }

  state.tools
    .filter((tool) => tool.status === 'approval')
    .forEach((tool) => {
      resolveApprovalTool(tool, event, Boolean(approved))
      upsertTurnTool(state, tool)
      upsertToolMessagePart(state, tool)
    })
}

export function finalizeToolActivitiesForRequest(
  state: ToolMutationState,
  requestId: string | null,
  timestamp: string,
  terminalStatus: 'cancelled' | 'failed',
  reason?: string,
) {
  if (!requestId) return
  const terminalReason = String(reason || '').trim()
  state.tools
    .filter((tool) => tool.requestId === requestId && isToolActivityInFlight(tool))
    .forEach((tool) => {
      tool.status = terminalStatus
      tool.eventType = 'tool_call_failed'
      tool.timestamp = timestamp
      tool.payload = {
        ...(tool.payload || {}),
        ...(terminalReason
          ? {
              error: tool.payload?.error || terminalReason,
              result: tool.payload?.result || {
                type: 'tool_observation',
                status: terminalStatus,
                tool_id: tool.toolName,
                tool_call_id: tool.toolCallId,
                message: terminalReason,
                execution_status: 'failed',
              },
            }
          : {}),
      }
      upsertTurnTool(state, tool)
      upsertToolMessagePart(state, tool)
    })
}

function isToolActivityInFlight(tool: ToolActivity): boolean {
  return tool.status === 'proposed' || tool.status === 'started' || tool.status === 'approval'
}

function toolEventWasUserCancelled(event: FactoryFrontendEvent): boolean {
  const payload = event.payload || {}
  const result = payload.result && typeof payload.result === 'object' ? payload.result : null
  const observation = payload.observation && typeof payload.observation === 'object' ? payload.observation : null
  const statusValues = [
    payload.status,
    payload.execution_status,
    result?.status,
    result?.execution_status,
    observation?.status,
    observation?.execution_status,
  ]
  if (statusValues.some((value) => String(value || '').trim().toLowerCase() === 'cancelled')) return true
  return [payload.error, result?.message, observation?.message]
    .some((value) => /user_cancelled|user-cancelled/i.test(String(value || '')))
}

function resolveApprovalTool(tool: ToolActivity, event: FactoryFrontendEvent, approved: boolean) {
  tool.approvalState = approved ? 'approved' : 'rejected'
  tool.eventType = event.event_type
  tool.timestamp = event.timestamp
  tool.payload = {
    ...(tool.payload || {}),
    approval: event.payload || {},
  }
}

function approvalToolCallIds(payload: Record<string, any> | undefined): string[] {
  const values = [
    payload?.tool_call_id,
    payload?.toolCallId,
    ...(Array.isArray(payload?.tool_call_ids) ? payload.tool_call_ids : []),
    ...(Array.isArray(payload?.toolCallIds) ? payload.toolCallIds : []),
  ]
  return Array.from(new Set(values.map((value) => String(value || '').trim()).filter(Boolean)))
}
