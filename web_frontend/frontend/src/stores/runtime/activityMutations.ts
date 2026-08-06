import type { FactoryFrontendEvent, RuntimeViewState } from '@/types/protocol'
import {
  applyKnowledgeEvent,
  applySchedulerEvent,
  type ResourceMutationState,
} from './resourceMutations'
import { contextWindowView } from './viewMappers'

type ActivityMutationState = Pick<
  RuntimeViewState,
  | 'contextActivity'
  | 'contextWindow'
  | 'debugEvents'
  | 'knowledgeActivity'
  | 'schedulerActivity'
  | 'timeline'
> & ResourceMutationState

export function applyContextActivityEvent(state: ActivityMutationState, event: FactoryFrontendEvent) {
  const type = event.event_type
  if (type === 'context_prepare_started') {
    state.contextActivity = { status: 'idle' }
  } else if (type === 'context_compression_started') {
    state.contextActivity.status = 'running'
    state.contextActivity.eventType = type
    state.contextActivity.payload = event.payload
  } else if (type === 'context_compression_completed') {
    state.contextActivity.status = 'completed'
    state.contextActivity.eventType = type
    state.contextActivity.payload = event.payload
  } else if (type === 'context_compression_failed') {
    state.contextActivity.status = 'failed'
    state.contextActivity.eventType = type
    state.contextActivity.payload = event.payload
  } else if (type === 'context_compression_skipped') {
    state.contextActivity.status = 'skipped'
    state.contextActivity.eventType = type
    state.contextActivity.payload = event.payload
  }
  if (type === 'context_window_updated') {
    state.contextWindow = contextWindowView(event)
  }
}

export function applyMemoryActivityEvent(
  state: Pick<RuntimeViewState, 'memoryActivity'>,
  event: FactoryFrontendEvent,
) {
  const type = event.event_type
  if (
    (type.includes('queued') && !type.includes('failed')) ||
    type === 'memory_segment_prepared' ||
    type === 'memory_extraction_completed'
  ) {
    state.memoryActivity.status = 'writing'
  } else if (type.includes('completed') || type === 'memory_retrieval_completed' || type === 'memory_injection_completed') {
    state.memoryActivity.status = 'completed'
  } else if (type.includes('failed')) {
    state.memoryActivity.status = 'failed'
  }
  state.memoryActivity.eventType = type
  state.memoryActivity.payload = event.payload
}

export function applyKnowledgeActivityEvent(state: ActivityMutationState, event: FactoryFrontendEvent) {
  state.knowledgeActivity.push({
    eventType: event.event_type,
    timestamp: event.timestamp,
    sourceId: event.payload?.source_id || null,
    jobId: event.payload?.job_id || null,
    mode: event.payload?.mode || null,
    phase: event.payload?.phase || null,
    status: event.payload?.status || null,
    reportPath: event.payload?.report_path || null,
    payload: event.payload || {},
  })
  applyKnowledgeEvent(state, event)
}

export function applySchedulerActivityEvent(state: ActivityMutationState, event: FactoryFrontendEvent) {
  state.schedulerActivity.push({
    eventType: event.event_type,
    timestamp: event.timestamp,
    jobId: event.payload?.job_id || null,
    runId: event.payload?.run_id || null,
    targetType: event.payload?.target_type || null,
    status: event.payload?.status || null,
    reportPath: event.payload?.report_path || null,
    payload: event.payload || {},
  })
  applySchedulerEvent(state, event)
}

export function recordDebugEvent(state: Pick<RuntimeViewState, 'debugEvents'>, event: FactoryFrontendEvent) {
  state.debugEvents.push(event)
  if (state.debugEvents.length > 100) {
    state.debugEvents.shift()
  }
}

export function recordTimelineEvent(state: Pick<RuntimeViewState, 'timeline'>, event: FactoryFrontendEvent) {
  if (!event.process_event) return
  state.timeline.push({
    id: event.event_id,
    eventType: event.event_type,
    timestamp: event.timestamp,
    spanId: event.span_id || null,
    parentSpanId: event.parent_span_id || null,
    stageId: event.stage_id || null,
    nodeId: event.node_id || null,
    nodeLabel: event.node_label || null,
    message: event.message || null,
    severity: event.severity || null,
    payload: event.payload || {},
  })
}
