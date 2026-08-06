import { requestJson } from './http'

export type BackgroundTaskType = 'sub_agent' | 'manufacture' | 'evolve'
export type BackgroundTaskStatus =
  | 'queued'
  | 'claimed'
  | 'running'
  | 'waiting_approval'
  | 'waiting_external'
  | 'cancelling'
  | 'succeeded'
  | 'failed'
  | 'cancelled'

export interface BackgroundTask {
  task_id: string
  session_id: string
  type: BackgroundTaskType
  status: BackgroundTaskStatus
  request_id: string
  task_text: string
  payload: Record<string, unknown>
  parent_task_id?: string | null
  parent_package_id?: string | null
  assignee_package_id?: string | null
  assignee_session_id?: string | null
  delivery_standard: Record<string, unknown>
  visible_context: Record<string, unknown>
  depends_on: string[]
  input_artifacts: Array<Record<string, unknown>>
  artifact_refs: Array<Record<string, unknown>>
  result_summary: string
  result?: Record<string, unknown> | null
  error?: { code?: string; message?: string; details?: Record<string, unknown> } | null
  pending_interaction?: PendingInteraction | null
  created_at: string
  updated_at: string
  started_at?: string | null
  completed_at?: string | null
  revision: number
}

export type PendingInteractionKind =
  | 'ask_user'
  | 'resource_request'
  | 'tool_approval'
  | 'publish_confirmation'
  | 'external_condition'
  | 'internal_wait'

export interface PendingInteraction {
  interaction_id: string
  kind: PendingInteractionKind
  title: string
  message: string
  source: Record<string, string>
  options: Array<{ value?: string; label?: string; description?: string }>
  requests: Array<Record<string, unknown>>
  resource_requests: Array<Record<string, unknown>>
  workspace_id?: string | null
  payload: Record<string, unknown>
}

export type InteractionAction = 'approve' | 'deny' | 'trust_tool' | 'revise' | 'answer' | 'continue'

export interface BackgroundTaskEvent {
  seq: number
  event_id: string
  event_type: string
  created_at: string
  request_id?: string | null
  task_id?: string | null
  session_id?: string | null
  payload: Record<string, unknown>
}

export interface BackgroundTaskSchedulerSettings {
  max_parallel_sub_agents: number
  revision: number
  updated_at: string
}

export const backgroundTasksApi = {
  settings: () =>
    requestJson<{ settings: BackgroundTaskSchedulerSettings }>('/api/background-tasks/settings'),
  updateSettings: (maxParallelSubAgents: number, revision?: number) =>
    requestJson<{ settings: BackgroundTaskSchedulerSettings }>('/api/background-tasks/settings', {
      method: 'PATCH',
      body: JSON.stringify({
        max_parallel_sub_agents: maxParallelSubAgents,
        ...(revision == null ? {} : { revision }),
      }),
    }),
  list: (params: { sessionId?: string; type?: BackgroundTaskType; status?: BackgroundTaskStatus[] } = {}) => {
    const query = new URLSearchParams()
    if (params.sessionId) query.set('session_id', params.sessionId)
    if (params.type) query.set('type', params.type)
    for (const status of params.status || []) query.append('status', status)
    const serialized = query.toString()
    const suffix = serialized ? `?${serialized}` : ''
    return requestJson<{ tasks: BackgroundTask[] }>(`/api/background-tasks${suffix}`)
  },
  get: (taskId: string) =>
    requestJson<{ task: BackgroundTask }>(`/api/background-tasks/${encodeURIComponent(taskId)}`),
  events: (taskId: string, after = 0) =>
    requestJson<{ events: BackgroundTaskEvent[] }>(
      `/api/background-tasks/${encodeURIComponent(taskId)}/events?after=${after}`,
    ),
  cancel: (taskId: string, reason?: string) =>
    requestJson<{ task: BackgroundTask }>(`/api/background-tasks/${encodeURIComponent(taskId)}/cancel`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    }),
  delete: (taskId: string) =>
    requestJson<{ task: BackgroundTask; deleted: boolean }>(
      `/api/background-tasks/${encodeURIComponent(taskId)}`,
      { method: 'DELETE' },
    ),
  resolveInteraction: (
    taskId: string,
    interactionId: string,
    action: InteractionAction,
    payload: Record<string, unknown> = {},
  ) =>
    requestJson<{ task: BackgroundTask }>(
      `/api/background-tasks/${encodeURIComponent(taskId)}/interactions/${encodeURIComponent(interactionId)}/resolve`, {
      method: 'POST',
      body: JSON.stringify({ action, payload }),
    }),
}
