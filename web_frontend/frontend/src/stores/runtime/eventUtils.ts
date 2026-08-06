import type { FactoryFrontendEvent } from '@/types/protocol'

const REQUEST_SCOPED_PREFIXES = [
  'run_',
  'node_',
  'stage_',
  'message_',
  'model_',
  'tool_',
  'plan_',
  'context_',
  'interrupt_',
  'runtime_request_',
  'runtime_paused',
  'runtime_resumed',
]

const USER_INPUT_INTERRUPT_TYPES = new Set([
  'create_agent_question',
  'agent_evolution_question',
])

const DEDICATED_INTERRUPT_PANEL_TYPES = new Set<string>()

const REQUEST_TERMINAL_EVENT_TYPES = new Set([
  'run_completed',
  'run_cancelled',
  'run_failed',
  'error',
  'interrupt_requested',
  'tool_approval_requested',
  // A stopped run can finish its in-flight tool cancellation immediately
  // after the stop request. These events are terminal for the individual
  // tool and must pass the request stop fence so the UI can close the card.
  'tool_call_completed',
  'tool_call_failed',
  'tool_contract_invalid',
  'tool_observation_available',
])

export function isRequestScopedEvent(eventType: string): boolean {
  return REQUEST_SCOPED_PREFIXES.some((prefix) => eventType.startsWith(prefix))
}

export function isRequestTerminalEvent(eventType: string): boolean {
  return REQUEST_TERMINAL_EVENT_TYPES.has(eventType)
}

export function isSchedulerRequest(requestId: string | null | undefined): boolean {
  return typeof requestId === 'string' && requestId.startsWith('scheduler-')
}

export function isBackgroundEvent(
  event: FactoryFrontendEvent,
  activeRequestId: string | null,
): boolean {
  return Boolean(
    event.request_id &&
    event.request_id !== activeRequestId &&
    isSchedulerRequest(event.request_id),
  )
}

export function isRestorableProcessStateEvent(eventType: string): boolean {
  return ['stage_', 'node_', 'plan_', 'context_', 'memory_'].some((prefix) => eventType.startsWith(prefix))
}

export function interruptType(event: FactoryFrontendEvent | null): string {
  return String(event?.payload?.type || '')
}

export function isUserInputInterrupt(event: FactoryFrontendEvent | null): boolean {
  return USER_INPUT_INTERRUPT_TYPES.has(interruptType(event))
}

export function shouldRenderInterruptMessage(event: FactoryFrontendEvent): boolean {
  return !DEDICATED_INTERRUPT_PANEL_TYPES.has(interruptType(event))
}

export function interruptMessage(event: FactoryFrontendEvent): string {
  return String(event.payload?.message || event.message || '').trim()
}
