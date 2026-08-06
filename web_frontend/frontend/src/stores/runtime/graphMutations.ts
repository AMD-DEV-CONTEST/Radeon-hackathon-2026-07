import type { FactoryFrontendEvent, RuntimeViewState } from '@/types/protocol'

type GraphMutationState = Pick<RuntimeViewState, 'nodes' | 'stages'>

export function applyStageStarted(state: GraphMutationState, event: FactoryFrontendEvent) {
  const stageId = event.stage_id
  if (!stageId) return

  state.stages[stageId] = {
    stageId,
    status: 'running',
    nodeId: event.node_id || null,
    startedAt: event.timestamp,
    completedAt: null,
    failedAt: null,
    lastEventType: event.event_type,
    lastMessage: event.message || null,
  }
}

export function applyStageCompleted(state: GraphMutationState, event: FactoryFrontendEvent) {
  const stageId = event.stage_id
  if (!stageId || !state.stages[stageId]) return

  state.stages[stageId].status = 'completed'
  state.stages[stageId].completedAt = event.timestamp
  state.stages[stageId].lastEventType = event.event_type
  state.stages[stageId].lastMessage = event.message || null
}

export function applyStageFailed(state: GraphMutationState, event: FactoryFrontendEvent) {
  const stageId = event.stage_id
  if (!stageId || !state.stages[stageId]) return

  state.stages[stageId].status = 'failed'
  state.stages[stageId].failedAt = event.timestamp
  state.stages[stageId].lastEventType = event.event_type
  state.stages[stageId].lastMessage = event.message || null
}

export function applyNodeStarted(state: GraphMutationState, event: FactoryFrontendEvent) {
  const nodeId = event.node_id
  if (!nodeId) return

  state.nodes[nodeId] = {
    nodeId,
    stageId: event.stage_id || null,
    status: 'running',
    label: event.node_label || null,
    kind: event.node_kind || null,
    startedAt: event.timestamp,
    completedAt: null,
    failedAt: null,
    message: event.message || null,
    payload: event.payload || {},
  }
}

export function applyNodeProgress(state: GraphMutationState, event: FactoryFrontendEvent) {
  const nodeId = event.node_id
  if (!nodeId) return

  if (!state.nodes[nodeId]) {
    state.nodes[nodeId] = {
      nodeId,
      stageId: event.stage_id || null,
      status: 'running',
      label: event.node_label || null,
      kind: event.node_kind || null,
      startedAt: event.timestamp,
      completedAt: null,
      failedAt: null,
      message: event.message || null,
      payload: event.payload || {},
    }
  } else {
    state.nodes[nodeId].message = event.message || null
    state.nodes[nodeId].payload = { ...state.nodes[nodeId].payload, ...event.payload }
  }
}

export function applyNodeCompleted(state: GraphMutationState, event: FactoryFrontendEvent) {
  const nodeId = event.node_id
  if (!nodeId || !state.nodes[nodeId]) return

  state.nodes[nodeId].status = 'completed'
  state.nodes[nodeId].completedAt = event.timestamp
  state.nodes[nodeId].message = event.message || null
  state.nodes[nodeId].payload = { ...state.nodes[nodeId].payload, ...event.payload }
}

export function applyNodeFailed(state: GraphMutationState, event: FactoryFrontendEvent) {
  const nodeId = event.node_id
  if (!nodeId) return

  if (!state.nodes[nodeId]) {
    state.nodes[nodeId] = {
      nodeId,
      stageId: event.stage_id || null,
      status: 'failed',
      label: event.node_label || null,
      kind: event.node_kind || null,
      startedAt: event.timestamp,
      completedAt: null,
      failedAt: event.timestamp,
      message: event.message || null,
      payload: event.payload || {},
    }
  } else {
    state.nodes[nodeId].status = 'failed'
    state.nodes[nodeId].failedAt = event.timestamp
    state.nodes[nodeId].message = event.message || null
    state.nodes[nodeId].payload = { ...state.nodes[nodeId].payload, ...event.payload }
  }
}
