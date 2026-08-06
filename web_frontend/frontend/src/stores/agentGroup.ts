/**
 * Agent 群聊系统 - Pinia Store
 *
 * 管理群聊状态、成员、消息、runs
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { ContextReferenceInput, FactoryFrontendEvent, RuntimeAttachmentInput, TranscriptItem, ChatMessagePart } from '@/types/protocol'
import { attachmentPart, reasoningPart, textPart, upsertPart } from '@/stores/runtime/messageParts'
import {
  agentGroupApi,
  type AgentGroupSessionView,
  type AgentGroupMessageView,
  type AgentView,
} from '@/api/agentGroup'

const ACTIVE_GROUP_STORAGE_KEY = 'fastagentfactory.activeAgentGroupId'

// 动态参与者视图（聚合 runs 信息）
export interface DynamicParticipantView {
  package_id: string
  agent_name: string
  agent_description?: string
  run_count: number
  active_run_count: number
  statuses: string[]
  session_ids: string[]
}

export const useAgentGroupStore = defineStore('agentGroup', () => {
  // ===== State =====
  const agents = ref<AgentView[]>([])
  const groups = ref<AgentGroupSessionView[]>([])
  const activeGroup = ref<AgentGroupSessionView | null>(null)
  const loading = ref(false)
  const saving = ref(false)
  const bootstrapped = ref(false)
  const error = ref<string | null>(null)
  // Runtime events are transient projections. Persisted group messages remain the source of truth.
  const liveMessages = ref<Record<string, TranscriptItem>>({})
  const pendingApprovals = ref<Record<string, FactoryFrontendEvent>>({})
  const bufferedRuntimeEvents = ref<Record<string, FactoryFrontendEvent[]>>({})

  // ===== Computed =====
  const members = computed(() => activeGroup.value?.members || [])
  const messages = computed(() => activeGroup.value?.messages || [])
  const runs = computed(() => activeGroup.value?.runs || [])
  const activeRuns = computed(() => runs.value.filter(r => ['queued', 'running', 'awaiting_approval'].includes(r.status)))
  const completedRuns = computed(() => runs.value.filter(r => ['completed', 'failed', 'cancelled'].includes(r.status)))
  const transcript = computed<TranscriptItem[]>(() => {
    const persisted = messages.value.map(message => messageToTranscript(
      message,
      message.speaker_package_id ? agentById(message.speaker_package_id)?.agent_name : undefined,
      agents.value.map(agent => agent.agent_name).filter((name): name is string => Boolean(name)),
    ))
    const activeRunIds = new Set(activeRuns.value.map(run => run.group_run_id))
    const live = Object.values(liveMessages.value)
      .filter(message => activeRunIds.has(String(message.metadata?.group_run_id || '')))
      .sort((left, right) => left.timestamp.localeCompare(right.timestamp))
    return [...persisted, ...live]
  })
  const approvalRequests = computed(() => Object.values(pendingApprovals.value))

  // 动态参与者列表（按 package_id 聚合 runs）
  const participants = computed<DynamicParticipantView[]>(() => {
    if (!activeGroup.value) return []

    const participantMap = new Map<string, DynamicParticipantView>()

    // 从成员初始化
    for (const member of activeGroup.value.members) {
      participantMap.set(member.package_id, {
        package_id: member.package_id,
        agent_name: member.agent_name || member.package_id,
        agent_description: member.agent_description,
        run_count: 0,
        active_run_count: 0,
        statuses: [],
        session_ids: [member.package_session_id],
      })
    }

    // 聚合 runs
    for (const run of activeGroup.value.runs) {
      const participant = participantMap.get(run.speaker_package_id)
      if (participant) {
        participant.run_count++
        if (['queued', 'running', 'awaiting_approval'].includes(run.status)) {
          participant.active_run_count++
        }
        if (!participant.statuses.includes(run.status)) {
          participant.statuses.push(run.status)
        }
      }
    }

    return Array.from(participantMap.values()).sort((a, b) => {
      // 按活跃 run 数量排序，然后按名称
      if (a.active_run_count !== b.active_run_count) {
        return b.active_run_count - a.active_run_count
      }
      return a.agent_name.localeCompare(b.agent_name)
    })
  })

  // ===== Actions =====
  const agentById = (packageId: string) => {
    return agents.value.find(a => a.package_id === packageId)
  }

  const refreshAgents = async () => {
    try {
      const { agents: fetchedAgents } = await agentGroupApi.agents()
      agents.value = fetchedAgents
    } catch (e) {
      error.value = errorMessage(e)
      throw e
    }
  }

  const refreshGroups = async () => {
    try {
      const { groups: fetchedGroups } = await agentGroupApi.groups()
      groups.value = fetchedGroups.sort((a, b) => {
        return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
      })

      // 自动加载保存的活动群聊
      if (!activeGroup.value && groups.value.length > 0) {
        const savedId = localStorage.getItem(ACTIVE_GROUP_STORAGE_KEY)
        const targetGroup = savedId
          ? groups.value.find(g => g.group_id === savedId)
          : groups.value[0]
        if (targetGroup) {
          await loadGroup(targetGroup.group_id)
        }
      }
    } catch (e) {
      error.value = errorMessage(e)
      throw e
    }
  }

  const bootstrap = async () => {
    if (bootstrapped.value || loading.value) return
    loading.value = true
    error.value = null
    try {
      await Promise.all([refreshAgents(), refreshGroups()])
      bootstrapped.value = true
    } catch (e) {
      error.value = errorMessage(e)
      throw e
    } finally {
      loading.value = false
    }
  }

  const createGroup = async (payload: {
    title: string
    member_package_ids: string[]
    workspace_id?: string
  }) => {
    saving.value = true
    error.value = null
    try {
      const { group } = await agentGroupApi.createGroup(payload)
      upsertGroup(group)
      setActiveGroup(group)
      return group
    } catch (e) {
      error.value = errorMessage(e)
      throw e
    } finally {
      saving.value = false
    }
  }

  const loadGroup = async (groupId: string) => {
    loading.value = true
    error.value = null
    try {
      const { group } = await agentGroupApi.group(groupId)
      upsertGroup(group)
      setActiveGroup(group)
      replayBufferedRuntimeEvents(groupId)
    } catch (e) {
      error.value = errorMessage(e)
      throw e
    } finally {
      loading.value = false
    }
  }

  const updateGroup = async (payload: { title?: string; status?: any }) => {
    if (!activeGroup.value) return
    saving.value = true
    error.value = null
    try {
      const { group } = await agentGroupApi.updateGroup(activeGroup.value.group_id, payload)
      replaceActive(group)
    } catch (e) {
      error.value = errorMessage(e)
      throw e
    } finally {
      saving.value = false
    }
  }

  const deleteGroup = async (groupId: string) => {
    saving.value = true
    error.value = null
    try {
      await agentGroupApi.deleteGroup(groupId)
      groups.value = groups.value.filter(g => g.group_id !== groupId)
      if (activeGroup.value?.group_id === groupId) {
        activeGroup.value = null
        localStorage.removeItem(ACTIVE_GROUP_STORAGE_KEY)
      }
      return { success: true }
    } catch (e) {
      error.value = errorMessage(e)
      throw e
    } finally {
      saving.value = false
    }
  }

  const addMember = async (packageId: string) => {
    if (!activeGroup.value) return
    saving.value = true
    error.value = null
    try {
      const { group } = await agentGroupApi.addMember(activeGroup.value.group_id, { package_id: packageId })
      replaceActive(group)
    } catch (e) {
      error.value = errorMessage(e)
      throw e
    } finally {
      saving.value = false
    }
  }

  const removeMember = async (packageId: string) => {
    if (!activeGroup.value) return
    saving.value = true
    error.value = null
    try {
      const { group } = await agentGroupApi.removeMember(activeGroup.value.group_id, packageId)
      replaceActive(group)
    } catch (e) {
      error.value = errorMessage(e)
      throw e
    } finally {
      saving.value = false
    }
  }

  const sendMessage = async (content: string, targetPackageIds: string[], replyToMessageId?: string, attachments: RuntimeAttachmentInput[] = []) => {
    if (!activeGroup.value) return
    saving.value = true
    error.value = null
    try {
      const clientMessageId = `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`
      const { group } = await agentGroupApi.sendMessage(activeGroup.value.group_id, {
        content,
        client_message_id: clientMessageId,
        target_package_ids: targetPackageIds,
        ...(replyToMessageId ? { reply_to_message_id: replyToMessageId } : {}),
        context_references: attachments.filter(attachment => (
          ['message_reference', 'workspace_file', 'text_selection'].includes(String(attachment.source_kind || ''))
          && typeof attachment.content === 'string'
        )) as ContextReferenceInput[],
      })
      replaceActive(group)
    } catch (e) {
      error.value = errorMessage(e)
      throw e
    } finally {
      saving.value = false
    }
  }

  const cancelRun = async (runId: string) => {
    if (!activeGroup.value) return
    saving.value = true
    error.value = null
    try {
      const { group } = await agentGroupApi.cancelRun(activeGroup.value.group_id, runId)
      replaceActive(group)
    } catch (e) {
      error.value = errorMessage(e)
      throw e
    } finally {
      saving.value = false
    }
  }

  const resumeRun = async (runId: string, payload: Record<string, unknown>) => {
    if (!activeGroup.value) return
    saving.value = true
    error.value = null
    try {
      const { group } = await agentGroupApi.resumeRun(activeGroup.value.group_id, runId, payload)
      replaceActive(group)
      delete pendingApprovals.value[runId]
    } catch (e) {
      error.value = errorMessage(e)
      throw e
    } finally {
      saving.value = false
    }
  }

  const retryRun = async (runId: string) => {
    if (!activeGroup.value) return
    saving.value = true
    error.value = null
    try {
      const { group } = await agentGroupApi.retryRun(activeGroup.value.group_id, runId)
      replaceActive(group)
    } catch (e) {
      error.value = errorMessage(e)
      throw e
    } finally {
      saving.value = false
    }
  }

  const applyRuntimeEvent = (event: FactoryFrontendEvent) => {
    const payload = event.payload || {}
    const groupId = String(payload.group_id || '').trim()
    const groupRunId = String(payload.group_run_id || '').trim()
    if (!groupId || !groupRunId) return
    if (activeGroup.value?.group_id !== groupId) {
      const previous = bufferedRuntimeEvents.value[groupId] || []
      bufferedRuntimeEvents.value = {
        ...bufferedRuntimeEvents.value,
        [groupId]: [...previous, event].slice(-500),
      }
      return
    }

    const run = activeGroup.value.runs.find(item => item.group_run_id === groupRunId)
    const display = speakerMetadata(run?.speaker_package_id)
    if (event.event_type === 'run_started') {
      patchRun(groupRunId, { status: 'running', request_id: event.request_id || undefined })
      return
    }
    if (event.event_type === 'tool_approval_requested') {
      patchRun(groupRunId, { status: 'awaiting_approval', request_id: event.request_id || undefined })
      pendingApprovals.value[groupRunId] = event
    }
    if (event.event_type === 'message_part_delta' || event.event_type === 'message_part_completed') {
      const messageId = String(payload.message_id || payload.stream_id || '').trim()
      const partId = String(payload.part_id || '').trim()
      if (!messageId || !partId) return
      const current = liveMessages.value[messageId] || createLiveMessage(messageId, event, groupRunId, display)
      const previous = current.parts.find(part => part.id === partId)
      const partType = String(payload.part_type || '')
      const nextText = event.event_type === 'message_part_delta'
        ? `${textFromPart(previous)}${String(payload.delta || '')}`
        : String(payload.content ?? payload.text ?? '')
      const part = partType === 'reasoning'
        ? reasoningPart(partId, nextText, { status: event.event_type === 'message_part_delta' ? 'streaming' : 'completed', timestamp: event.timestamp })
        : textPart(partId, nextText, { format: payload.format === 'plain' ? 'plain' : 'markdown', status: event.event_type === 'message_part_delta' ? 'streaming' : 'completed', timestamp: event.timestamp })
      liveMessages.value = { ...liveMessages.value, [messageId]: { ...current, parts: upsertPart(current.parts, part), content: textContent(upsertPart(current.parts, part)), timestamp: event.timestamp } }
      return
    }
    if (isToolEvent(event.event_type)) {
      const messageId = `group-tool-${groupRunId}-${String(payload.tool_call_id || event.span_id || event.event_id)}`
      const current = liveMessages.value[messageId] || createLiveMessage(messageId, event, groupRunId, display)
      const toolName = String(payload.tool_name || payload.tool_id || payload.name || 'tool')
      const toolCallId = String(payload.tool_call_id || '') || null
      const status = toolStatus(event.event_type)
      const callPartId = `${messageId}:call`
      const previousCall = current.parts.find(part => part.id === callPartId)
      const callPart: ChatMessagePart = {
        id: callPartId, type: 'tool_call', toolName, callId: toolCallId,
        arguments: payload.arguments || payload.args || {}, status,
        liveOutput: event.event_type === 'tool_call_output_delta'
          ? payload.output || null
          : previousCall?.type === 'tool_call' ? previousCall.liveOutput : undefined,
        createdAt: previousCall?.createdAt || current.timestamp,
        startedAt: previousCall?.startedAt || (event.event_type === 'tool_call_started' ? event.timestamp : null),
        updatedAt: event.timestamp,
      }
      let parts = upsertPart(current.parts, callPart)
      if (event.event_type === 'tool_observation_available' || event.event_type === 'tool_call_failed' || event.event_type === 'tool_call_completed') {
        parts = upsertPart(parts, {
          id: `${messageId}:result`, type: 'tool_result', toolName, callId: toolCallId,
          output: payload.output || payload.result || payload.observation || null,
          error: payload.error || null, status: event.event_type === 'tool_call_failed' ? 'failed' : 'completed',
          createdAt: event.timestamp, updatedAt: event.timestamp,
        })
      }
      liveMessages.value = { ...liveMessages.value, [messageId]: { ...current, parts, status: status === 'failed' ? 'failed' : status === 'completed' ? 'completed' : 'streaming', timestamp: event.timestamp } }
      return
    }
    if (['run_completed', 'run_failed', 'run_cancelled'].includes(event.event_type)) {
      patchRun(groupRunId, { status: event.event_type === 'run_completed' ? 'completed' : event.event_type === 'run_cancelled' ? 'cancelled' : 'failed' })
      delete pendingApprovals.value[groupRunId]
      void loadGroup(groupId).finally(() => {
        const remaining = { ...liveMessages.value }
        for (const [id, message] of Object.entries(remaining)) {
          if (message.metadata?.group_run_id === groupRunId) delete remaining[id]
        }
        liveMessages.value = remaining
      })
    }
  }

  // 内部辅助方法
  const upsertGroup = (group: AgentGroupSessionView) => {
    const index = groups.value.findIndex(g => g.group_id === group.group_id)
    if (index >= 0) {
      groups.value[index] = group
    } else {
      groups.value.unshift(group)
    }
  }

  const setActiveGroup = (group: AgentGroupSessionView) => {
    activeGroup.value = group
    localStorage.setItem(ACTIVE_GROUP_STORAGE_KEY, group.group_id)
  }

  const replaceActive = (group: AgentGroupSessionView) => {
    upsertGroup(group)
    if (activeGroup.value?.group_id === group.group_id) {
      activeGroup.value = group
    }
  }

  const patchRun = (runId: string, patch: Record<string, unknown>) => {
    if (!activeGroup.value) return
    const runs = activeGroup.value.runs.map(run => run.group_run_id === runId ? { ...run, ...patch } : run)
    activeGroup.value = { ...activeGroup.value, runs }
    upsertGroup(activeGroup.value)
  }

  const replayBufferedRuntimeEvents = (groupId: string) => {
    const events = bufferedRuntimeEvents.value[groupId] || []
    if (!events.length) return
    const remaining = { ...bufferedRuntimeEvents.value }
    delete remaining[groupId]
    bufferedRuntimeEvents.value = remaining
    events.forEach(applyRuntimeEvent)
  }

  const speakerMetadata = (packageId?: string) => {
    const agent = packageId ? agentById(packageId) : null
    const name = agent?.agent_name || packageId || 'Assistant'
    return { display_name: name, avatar_label: name.slice(0, 2), agent_group_speaker: true, package_id: packageId }
  }

  const applyGroupSnapshot = (group: AgentGroupSessionView) => {
    upsertGroup(group)
    if (activeGroup.value?.group_id === group.group_id) {
      activeGroup.value = group
    }
  }

  return {
    // State
    agents,
    groups,
    activeGroup,
    loading,
    saving,
    bootstrapped,
    error,

    // Computed
    members,
    messages,
    runs,
    activeRuns,
    completedRuns,
    transcript,
    approvalRequests,
    participants,

    // Actions
    agentById,
    refreshAgents,
    refreshGroups,
    bootstrap,
    createGroup,
    loadGroup,
    updateGroup,
    deleteGroup,
    addMember,
    removeMember,
    sendMessage,
    cancelRun,
    resumeRun,
    retryRun,
    applyRuntimeEvent,
    applyGroupSnapshot,
  }
})

function messageToTranscript(message: AgentGroupMessageView, agentName?: string, mentionNames: string[] = []): TranscriptItem {
  const role = message.speaker_type === 'user' ? 'user' : message.speaker_type === 'system' ? 'system' : 'assistant'
  const displayName = message.speaker_type === 'agent' ? agentName || message.speaker_package_id || 'Assistant' : undefined
  const references = (message.context_references || []).map(reference => ({
    kind: reference.kind,
    name: reference.name,
    source_kind: reference.source_kind,
    mime_type: reference.mime_type,
  }))
  const timestamp = message.created_at
  return {
    id: `group-message-${message.message_id}`,
    role,
    content: message.content,
    timestamp,
    status: 'completed',
    parts: [
      textPart(`group-message-${message.message_id}:text`, message.content, { timestamp }),
      ...references.map((reference, index) => attachmentPart(`group-message-${message.message_id}:reference:${index}`, reference, timestamp)),
    ],
    attachments: references,
    metadata: {
      group_message_id: message.message_id,
      group_run_id: message.group_run_id,
      reply_to_message_id: message.reply_to_message_id,
      package_id: message.speaker_package_id,
      display_name: displayName,
      avatar_label: displayName?.slice(0, 2),
      agent_group_speaker: message.speaker_type === 'agent',
      agent_group_message: true,
      mention_names: mentionNames,
    },
  }
}

function createLiveMessage(messageId: string, event: FactoryFrontendEvent, groupRunId: string, metadata: Record<string, unknown>): TranscriptItem {
  return { id: messageId, role: 'assistant', content: '', timestamp: event.timestamp, status: 'streaming', parts: [], streamId: messageId, metadata: { ...metadata, group_run_id: groupRunId, request_id: event.request_id } }
}

function textFromPart(part: ChatMessagePart | undefined): string {
  return part?.type === 'text' || part?.type === 'reasoning' ? part.text : ''
}

function textContent(parts: ChatMessagePart[]): string {
  return parts.filter((part): part is Extract<ChatMessagePart, { type: 'text' }> => part.type === 'text').map(part => part.text).join('')
}

function isToolEvent(eventType: string): boolean {
  return ['tool_call_proposed', 'tool_call_started', 'tool_call_output_delta', 'tool_call_completed', 'tool_observation_available', 'tool_call_failed', 'tool_approval_requested'].includes(eventType)
}

function toolStatus(eventType: string): ChatMessagePart['status'] {
  if (eventType === 'tool_call_failed') return 'failed'
  if (eventType === 'tool_call_completed' || eventType === 'tool_observation_available') return 'completed'
  if (eventType === 'tool_approval_requested') return 'awaiting_approval'
  return eventType === 'tool_call_proposed' ? 'requested' : 'running'
}

function errorMessage(exc: unknown): string {
  if (exc instanceof Error) return exc.message
  if (typeof exc === 'string') return exc
  return String(exc)
}
