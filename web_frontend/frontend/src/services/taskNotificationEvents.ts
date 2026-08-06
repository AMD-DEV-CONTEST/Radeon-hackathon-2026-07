import { useAgentGroupStore } from '@/stores/agentGroup'
import { isSchedulerRequest } from '@/stores/runtime/eventUtils'
import { scopeFromEventPayload } from '@/stores/runtime/scopes'
import { schedulerRunNoticeView } from '@/stores/runtime/viewMappers'
import type { FactoryFrontendEvent, FactoryMode } from '@/types/protocol'
import {
  publishTaskNotification,
  type TaskNotificationStatus,
  type TaskTerminalNotification,
} from './taskNotifications'

export type TaskNotificationEventContext = Record<string, never>
const TERMINAL_SCHEDULER_EVENTS = new Set([
  'scheduler_run_completed',
  'scheduler_run_failed',
  'scheduler_run_skipped',
  'scheduler_run_cancelled',
])

export function captureTaskNotificationEventContext(
  _event: FactoryFrontendEvent,
): TaskNotificationEventContext {
  return {}
}

export function publishTaskNotificationsForEvent(
  event: FactoryFrontendEvent,
  _context: TaskNotificationEventContext,
): void {
  if (event.payload?.group_id && event.payload?.group_run_id) {
    const notification = groupRunNotification(event)
    if (notification) publishTaskNotification(notification)
    return
  }
  if (TERMINAL_SCHEDULER_EVENTS.has(event.event_type)) {
    const notification = schedulerNotification(event)
    if (notification) publishTaskNotification(notification)
    return
  }
  const notification = conversationNotification(event)
  if (notification) publishTaskNotification(notification)
}

function conversationNotification(event: FactoryFrontendEvent): TaskTerminalNotification | null {
  const status = runTerminalStatus(event)
  if (!status || isSchedulerRequest(event.request_id)) return null
  const finishStatus = text(event.payload?.finish_status || event.payload?.status)
  if (finishStatus === 'waiting_for_workers') return null

  const mode = normalizedMode(event.mode)
  const sessionId = conversationSessionId(event, mode)
  const packageId = mode === 'agent_package'
    ? text(event.payload?.package_id || event.payload?.agent_session?.package_id)
    : null
  return {
    key: `conversation:${event.request_id || event.event_id}:${status}`,
    category: 'conversation',
    status,
    subject: text(event.payload?.package_name || event.payload?.agent_session?.package_name),
    body: eventSummary(event),
    target: {
      kind: 'conversation',
      mode,
      sessionId,
      packageId,
      conversationScope: scopeFromEventPayload(event),
    },
  }
}

function groupRunNotification(event: FactoryFrontendEvent): TaskTerminalNotification | null {
  const status = runTerminalStatus(event)
  if (!status) return null
  const groupId = text(event.payload?.group_id)
  const groupRunId = text(event.payload?.group_run_id)
  if (!groupId || !groupRunId) return null
  const store = useAgentGroupStore()
  const run = store.activeGroup?.runs.find((item) => item.group_run_id === groupRunId)
  const packageId = text(event.payload?.package_id || run?.speaker_package_id)
  return {
    key: `agent-group-run:${groupRunId}:${status}`,
    category: 'agentGroup',
    status,
    subject: packageId ? store.agentById(packageId)?.agent_name || packageId : null,
    body: eventSummary(event),
    target: { kind: 'agentGroup', groupId },
  }
}

function schedulerNotification(event: FactoryFrontendEvent): TaskTerminalNotification | null {
  const notice = schedulerRunNoticeView(event)
  if (!notice) return null
  const status = notificationStatus(notice.status)
  if (!status) return null
  return {
    key: `scheduler:${notice.id}:${status}`,
    category: 'scheduler',
    status,
    subject: notice.title,
    body: notice.summary,
    target: { kind: 'scheduler' },
  }
}

function runTerminalStatus(event: FactoryFrontendEvent): TaskNotificationStatus | null {
  if (event.event_type === 'run_failed') return 'failed'
  if (event.event_type === 'run_cancelled') return 'cancelled'
  if (event.event_type !== 'run_completed') return null
  const reported = text(event.payload?.finish_status || event.payload?.status)
  return reported === 'stopped' || reported === 'cancelled' ? 'cancelled' : 'completed'
}

function notificationStatus(value: string): TaskNotificationStatus | null {
  if (value === 'completed') return 'completed'
  if (value === 'failed') return 'failed'
  if (value === 'cancelled') return 'cancelled'
  if (value === 'skipped') return 'skipped'
  return null
}

function normalizedMode(
  mode: FactoryMode | null,
): 'create_agent' | 'evolve_agent' | 'agent_package' {
  if (mode === 'create_agent' || mode === 'evolve_agent' || mode === 'agent_package') return mode
  return 'agent_package'
}

function conversationSessionId(
  event: FactoryFrontendEvent,
  mode: 'create_agent' | 'evolve_agent' | 'agent_package',
): string | null {
  if (mode === 'agent_package') {
    return text(
      event.payload?.agent_session?.session_id
      || event.payload?.session_id
      || event.session_id,
    )
  }
  return text(
    event.payload?.factory_session_id
    || event.payload?.session?.session_id
    || event.payload?.session_id
    || event.session_id,
  )
}

function eventSummary(event: FactoryFrontendEvent): string | null {
  return text(
    event.payload?.output_summary
    || event.payload?.result_summary
    || event.payload?.summary
    || event.payload?.error_summary
    || event.payload?.error_message
    || event.payload?.error
    || event.message,
  )
}

function text(value: unknown): string | null {
  const normalized = String(value || '').trim()
  return normalized || null
}
