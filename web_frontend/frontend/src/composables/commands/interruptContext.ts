import type { ResumeInterruptOptions } from '@/api/commands'
import type { ActiveRequestView, FactoryFrontendEvent, FactoryMode } from '@/types/protocol'

interface InterruptContextState {
  activeRequests: Record<string, ActiveRequestView>
  currentMode: FactoryMode | null
  pendingInterrupt: FactoryFrontendEvent | null
}

export function withPendingInterruptContext(
  state: InterruptContextState,
  payload: ResumeInterruptOptions,
): ResumeInterruptOptions {
  const pending = state.pendingInterrupt
  if (!pending) return payload

  const pendingPayload = pending.payload || {}
  const originalRequest = pending.request_id ? state.activeRequests[pending.request_id] : null
  const requests = Array.isArray(pendingPayload.requests) ? pendingPayload.requests : []
  const toolCallIds = requests
    .map((request: any) => String(request?.tool_call_id || '').trim())
    .filter(Boolean)
  const firstRequest = requests[0] && typeof requests[0] === 'object' ? requests[0] : {}
  const mode = pending.mode || state.currentMode || undefined
  const runtimeSessionId = mode === 'agent_package' || mode === 'evolve_agent'
    ? pending.session_id || undefined
    : undefined

  return {
    ...payload,
    type: pendingPayload.type || 'tool_approval',
    mode,
    package_id:
      pendingPayload.package_id ||
      pendingPayload.agent_session?.package_id ||
      originalRequest?.payload?.package_id,
    session_id: runtimeSessionId,
    agent_session_id: pendingPayload.agent_session?.session_id || (mode === 'agent_package' ? pending.session_id : undefined),
    frontend_session_id: pending.session_id || undefined,
    interrupt_id: pendingPayload.interrupt_id || undefined,
    interrupt_event_id: pending.event_id,
    pending_request_id: pending.request_id || undefined,
    original_request_id: pending.request_id || undefined,
    tool_call_id: payload.tool_call_id || firstRequest.tool_call_id || undefined,
    tool_name: payload.tool_name || firstRequest.tool_name || firstRequest.tool_id || undefined,
    tool_call_ids: toolCallIds.length > 0 ? toolCallIds : undefined,
    requests,
  }
}
