import type { FactoryFrontendEvent, RuntimeViewState } from '@/types/protocol'
import {
  extensionItemView,
  knowledgeDocumentView,
  knowledgeSearchResultView,
  knowledgeSourceView,
  schedulerJobView,
  schedulerRunNoticeView,
  schedulerToolOptionView,
  toolPermissionsView,
  workspaceEntryView,
  workspaceFileView,
  workspaceRootView,
} from './viewMappers'

export type ResourceMutationState = Pick<
  RuntimeViewState,
  | 'extensionItems'
  | 'extensionTestResult'
  | 'extensionBindings'
  | 'toolPermissions'
  | 'knowledgeDocument'
  | 'knowledgeDocuments'
  | 'knowledgeResults'
  | 'knowledgeSources'
  | 'schedulerJobs'
  | 'schedulerRunNotices'
  | 'activeConversationScope'
  | 'activeFactorySessionId'
  | 'activeAgentSessionId'
  | 'schedulerToolOptions'
  | 'workspaceEntries'
  | 'workspaceFile'
  | 'workspaceRoots'
>

const SCHEDULER_NOTICE_EVENTS = new Set([
  'scheduler_run_scheduled',
  'scheduler_run_started',
  'scheduler_run_completed',
  'scheduler_run_failed',
  'scheduler_run_skipped',
  'scheduler_run_cancelled',
])

export function applyKnowledgeEvent(state: ResourceMutationState, event: FactoryFrontendEvent) {
  updateKnowledgeSources(state, event)
  if (event.event_type === 'knowledge_documents_listed') {
    const documents = event.payload?.documents || []
    state.knowledgeDocuments = Array.isArray(documents)
      ? documents.map(knowledgeDocumentView)
      : []
  } else if (event.event_type === 'knowledge_search_completed') {
    const results = event.payload?.results || []
    state.knowledgeResults = Array.isArray(results)
      ? results.map(knowledgeSearchResultView)
      : []
  } else if (event.event_type === 'knowledge_document_read') {
    state.knowledgeDocument = event.payload || null
  }
}

export function applyWorkspaceEvent(state: ResourceMutationState, event: FactoryFrontendEvent) {
  if (event.event_type === 'workspace_roots_listed') {
    const roots = event.payload?.roots || []
    state.workspaceRoots = Array.isArray(roots)
      ? roots.map(workspaceRootView)
      : []
  } else if (event.event_type === 'workspace_entries_listed') {
    const entries = event.payload?.entries || []
    state.workspaceEntries = Array.isArray(entries)
      ? entries.map(workspaceEntryView)
      : []
  } else if (event.event_type === 'workspace_file_read') {
    state.workspaceFile = workspaceFileView(event.payload || {})
  }
}

export function applyExtensionsEvent(state: ResourceMutationState, event: FactoryFrontendEvent) {
  if (event.event_type === 'extension_config_test_output_delta') {
    const requestId = String(event.request_id || '')
    const serverId = String(event.payload?.server_id || '')
    const line = String(event.payload?.line || '').trim()
    if (!requestId || !serverId || !line) return

    const current = state.extensionTestResult?.request_id === requestId
      ? state.extensionTestResult
      : {
          status: 'running',
          request_id: requestId,
          message: line,
          tests: [],
        }
    const tests = Array.isArray(current.tests) ? [...current.tests] : []
    const testIndex = tests.findIndex((test: any) => test?.server_id === serverId)
    const test = testIndex >= 0
      ? { ...tests[testIndex] }
      : {
          server_id: serverId,
          status: 'running',
          message: line,
          stderr: [],
          tools: [],
          tool_count: 0,
        }

    test.status = 'running'
    test.message = line
    test.stderr = [...(Array.isArray(test.stderr) ? test.stderr : []), line]
    if (testIndex >= 0) tests[testIndex] = test
    else tests.push(test)

    state.extensionTestResult = {
      ...current,
      status: 'running',
      request_id: requestId,
      message: line,
      tests,
    }
    return
  }

  const mcpServers = Array.isArray(event.payload?.mcp_servers) ? event.payload?.mcp_servers : []
  const skills = Array.isArray(event.payload?.skills) ? event.payload?.skills : []
  state.extensionItems = [
    ...mcpServers.map((item: any) => extensionItemView(item, 'mcp')),
    ...skills.map((item: any) => extensionItemView(item, 'skill')),
  ]
  state.extensionBindings = {
    mcp_server_ids: Array.isArray(event.payload?.bindings?.mcp_server_ids)
      ? event.payload.bindings.mcp_server_ids.map(String)
      : [],
    skill_ids: Array.isArray(event.payload?.bindings?.skill_ids)
      ? event.payload.bindings.skill_ids.map(String)
      : [],
  }
  state.toolPermissions = toolPermissionsView(event.payload?.tool_permissions)
  if (event.event_type === 'extension_config_tested') {
    state.extensionTestResult = event.payload?.test || event.payload?.install || event.payload || null
  } else if (event.event_type === 'extension_config_updated') {
    state.extensionTestResult = null
  }
}

export function applySchedulerEvent(state: ResourceMutationState, event: FactoryFrontendEvent) {
  updateSchedulerJobs(state, event)
  updateSchedulerOptions(state, event)
  updateSchedulerRunNotices(state, event)
}

export function markSchedulerRunNoticeRead(state: ResourceMutationState, noticeId: string) {
  const notice = state.schedulerRunNotices.find((item) => item.id === noticeId)
  if (notice) {
    notice.unread = false
  }
}

export function dismissSchedulerRunNoticeFromConversation(state: ResourceMutationState, noticeId: string) {
  const notice = state.schedulerRunNotices.find((item) => item.id === noticeId)
  if (notice) {
    notice.conversationScope = null
  }
}

function updateKnowledgeSources(state: ResourceMutationState, event: FactoryFrontendEvent) {
  if (Array.isArray(event.payload?.sources)) {
    state.knowledgeSources = event.payload.sources.map((source: any) => knowledgeSourceView(source, event.timestamp))
    return
  }
  if (event.event_type === 'knowledge_source_removed') {
    const sourceId = event.payload?.source_id
    if (sourceId) {
      state.knowledgeSources = state.knowledgeSources.filter((source) => source.payload?.source_id !== sourceId)
      state.knowledgeDocuments = state.knowledgeDocuments.filter((document) => document.payload?.source_id !== sourceId)
      state.knowledgeResults = state.knowledgeResults.filter((result) => result.payload?.source_id !== sourceId)
    }
    return
  }

  if (event.event_type.startsWith('knowledge_ingestion_') || event.event_type === 'knowledge_source_ready') {
    const sourceId = String(event.payload?.source_id || '').trim()
    if (!sourceId) return
    const index = state.knowledgeSources.findIndex((source) => String(source.payload?.source_id || '') === sourceId)
    if (index < 0) return
    const current = state.knowledgeSources[index]
    const counts = event.payload?.counts && typeof event.payload.counts === 'object'
      ? event.payload.counts
      : {}
    const status = event.event_type === 'knowledge_source_ready' || event.event_type === 'knowledge_ingestion_completed'
      ? 'ready'
      : event.event_type === 'knowledge_ingestion_failed'
        ? 'failed'
        : event.event_type === 'knowledge_ingestion_queued'
          ? 'registered'
          : 'indexing'
    state.knowledgeSources[index] = {
      ...current,
      status,
      documentCount: counts.documents_loaded ?? current.documentCount,
      updatedAt: event.timestamp,
      payload: {
        ...current.payload,
        source_id: sourceId,
        status,
        counts,
      },
    }
    return
  }

  const source = event.payload?.source || event.payload?.preview || null
  const sourceId = event.payload?.source_id || source?.source_id
  if (!sourceId && !source?.display_name) return

  const item = knowledgeSourceView(source || event.payload, event.timestamp)
  const key = String(sourceId || item.name)
  const index = state.knowledgeSources.findIndex((value) => String(value.payload?.source_id || value.name) === key)
  if (index >= 0) {
    state.knowledgeSources[index] = item
  } else {
    state.knowledgeSources.unshift(item)
  }
}

function updateSchedulerJobs(state: ResourceMutationState, event: FactoryFrontendEvent) {
  if (event.event_type === 'scheduler_job_deleted') {
    const jobId = event.payload?.job_id
    state.schedulerJobs = state.schedulerJobs.filter((item) => item.payload?.job_id !== jobId)
    return
  }
  const jobs = event.payload?.payload?.jobs || event.payload?.jobs
  if (Array.isArray(jobs)) {
    state.schedulerJobs = jobs.map(schedulerJobView)
    return
  }
  const job = event.payload?.payload?.job || event.payload?.job
  if (!job) return

  const view = schedulerJobView(job)
  const index = state.schedulerJobs.findIndex((item) => item.payload?.job_id === job.job_id)
  if (index >= 0) {
    state.schedulerJobs[index] = view
  } else {
    state.schedulerJobs.unshift(view)
  }
}

function updateSchedulerOptions(state: ResourceMutationState, event: FactoryFrontendEvent) {
  if (event.event_type !== 'scheduler_options_listed') return
  const tools = event.payload?.payload?.tools || event.payload?.tools || []
  state.schedulerToolOptions = Array.isArray(tools)
    ? tools
        .map(schedulerToolOptionView)
        .filter((tool): tool is NonNullable<ReturnType<typeof schedulerToolOptionView>> => tool !== null)
    : []
}

function updateSchedulerRunNotices(state: ResourceMutationState, event: FactoryFrontendEvent) {
  if (!SCHEDULER_NOTICE_EVENTS.has(event.event_type)) return

  const notice = schedulerRunNoticeView(event)
  if (!notice) return
  const index = state.schedulerRunNotices.findIndex((item) => item.id === notice.id)
  if (index >= 0) {
    state.schedulerRunNotices[index] = {
      ...state.schedulerRunNotices[index],
      ...notice,
      unread: notice.status === 'running' ? state.schedulerRunNotices[index].unread : true,
      conversationScope: state.schedulerRunNotices[index].conversationScope,
    }
  } else {
    notice.conversationScope = activeConversationScope(state)
    state.schedulerRunNotices.unshift(notice)
  }
  if (state.schedulerRunNotices.length > 30) {
    state.schedulerRunNotices = state.schedulerRunNotices.slice(0, 30)
  }
}

function activeConversationScope(state: ResourceMutationState): string | null {
  if (!state.activeFactorySessionId && !state.activeAgentSessionId) return null
  return state.activeConversationScope
}
