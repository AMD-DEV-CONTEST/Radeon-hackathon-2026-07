import { computed } from 'vue'
import { useI18n } from '@/composables/useI18n'
import { useRuntimeStore } from '@/stores/runtime'
import type { ChatMessagePart, ToolActivity, TranscriptItem } from '@/types/protocol'
import { isToolActivityActive, isToolActivityPendingApproval } from '@/utils/toolActivityState'
import { textPart } from '@/stores/runtime/messageParts'
import { conversationVisibleParts } from '@/utils/toolPresentation'

export type FactoryTimelineItem =
  | { kind: 'message'; id: string; timestamp: string; order: number; message: TranscriptItem }

export function useFactoryMessageProjection() {
  const runtimeStore = useRuntimeStore()
  const { t } = useI18n()

  const activeStreams = computed(() => {
    return Object.values(runtimeStore.modelStreams).filter(
      (stream) => (
        stream.visibleToUser
        && stream.active
        && requestOwnsActivePresentation(stream.requestId)
      ),
    )
  })
  const hasActiveStreams = computed(() => activeStreams.value.length > 0)
  const timelineItems = computed<FactoryTimelineItem[]>(() => {
    const items: FactoryTimelineItem[] = []
    runtimeStore.transcript.forEach((message, index) => {
      if (['queued', 'steering'].includes(String(message.metadata?.dispatch_state || ''))) return
      if (conversationVisibleParts(message.parts).length === 0) return
      items.push({
        kind: 'message',
        id: message.id,
        timestamp: message.timestamp,
        order: index,
        message,
      })
    })
    return items.sort(compareTimelineItems)
  })
  const thinkingMessages = computed<TranscriptItem[]>(() => {
    if (!runtimeStore.hasActiveRun || runtimeStore.isAwaitingUserInputInterrupt) return []
    const activeTurn = runtimeStore.activeTurn
    if (!activeTurn?.userMessage) return []
    if (!requestOwnsActivePresentation(activeTurn.requestId)) return []
    if (activeTurn.assistantMessages.some(messageHasDisplayParts)) return []
    const displayStatus = activeRuntimeDisplayStatus(runtimeStore.nodes, runtimeStore.contextActivity, t)
    const statusText = displayStatus.text
    return [
      {
        id: `thinking-${activeTurn.id}`,
        role: displayStatus.role,
        content: statusText,
        timestamp: activeTurn.startedAt || new Date().toISOString(),
        status: 'streaming',
        parts: [
          textPart(`thinking-${activeTurn.id}:status`, statusText, {
            format: 'plain',
            status: 'streaming',
            timestamp: activeTurn.startedAt || new Date().toISOString(),
          }),
        ],
        metadata: {
          thinking: true,
          request_id: activeTurn.requestId,
        },
      },
    ]
  })
  const hasApprovalRequests = computed(() => runtimeStore.currentApprovalRequests.length > 0)
  const runningToolActivities = computed(() => {
    return runtimeStore.tools.filter(
      (tool) => isToolActivityRunning(tool) && requestOwnsActivePresentation(tool.requestId),
    )
  })
  const toolActivityHint = computed(() => {
    if (!runtimeStore.hasActiveRun || runningToolActivities.value.length === 0) return ''
    if (runningToolActivities.value.some((tool) => isToolActivityPendingApproval(tool))) return t('factory.waitToolApproval')
    if (runningToolActivities.value.some((tool) => isKnowledgeRetrievalTool(tool))) return t('factory.knowledgeRetrieving')
    return runningToolActivities.value.length > 1
      ? t('factory.toolsRunning', { count: runningToolActivities.value.length })
      : t('factory.toolRunning')
  })
  const activeStreamContentKey = computed(() => {
    return [
      runtimeStore.transcript.map(messagePartsKey).join('|'),
      toolActivityHint.value,
      thinkingMessages.value.map(message => message.content).join('|'),
    ].join('')
  })

  function isMessageStreaming(streamId?: string): boolean {
    if (!streamId) return false
    const stream = runtimeStore.modelStreams[streamId]
    return Boolean(stream?.active && requestOwnsActivePresentation(stream.requestId))
  }

  function requestOwnsActivePresentation(requestId?: string | null): boolean {
    if (!runtimeStore.hasActiveRun || !runtimeStore.activeRequestId) return false
    if (requestId && requestId !== runtimeStore.activeRequestId) return false
    const request = runtimeStore.activeRequests[runtimeStore.activeRequestId]
    return Boolean(
      request
      && request.status === 'running'
      && !request.payload?.stop_requested_at
      && !['stopped', 'cancelled'].includes(String(request.payload?.dispatch_state || '')),
    )
  }

  return {
    activeStreamContentKey,
    hasActiveStreams,
    hasApprovalRequests,
    isMessageStreaming,
    thinkingMessages,
    timelineItems,
    toolActivityHint,
  }
}

function activeRuntimeDisplayStatus(
  nodes: ReturnType<typeof useRuntimeStore>['nodes'],
  contextActivity: ReturnType<typeof useRuntimeStore>['contextActivity'],
  t: ReturnType<typeof useI18n>['t'],
): { text: string; role: 'assistant' | 'system' } {
  if (
    contextActivity.status === 'running'
    && contextActivity.eventType === 'context_compression_started'
  ) {
    return { text: t('context.context_compression_started'), role: 'system' }
  }
  const activeNode = Object.values(nodes)
    .filter(node => node.status === 'running' && node.payload?.visible_to_user !== false)
    .sort((left, right) => Date.parse(right.startedAt) - Date.parse(left.startedAt))[0]
  const statusKey = String(activeNode?.payload?.status_key || '')
  if (statusKey === 'runtime_initialization') {
    return { text: t('factory.status.runtimeInitialization'), role: 'system' }
  }
  if (statusKey === 'intent_analysis') {
    return { text: t('factory.status.intentAnalysis'), role: 'assistant' }
  }
  if (statusKey === 'task_analysis') {
    return { text: t('factory.status.taskAnalysis'), role: 'assistant' }
  }
  return { text: t('roles.assistantThinking'), role: 'assistant' }
}

function compareTimelineItems(left: FactoryTimelineItem, right: FactoryTimelineItem): number {
  const leftTime = Date.parse(left.timestamp)
  const rightTime = Date.parse(right.timestamp)
  const normalizedLeft = Number.isFinite(leftTime) ? leftTime : 0
  const normalizedRight = Number.isFinite(rightTime) ? rightTime : 0
  if (normalizedLeft !== normalizedRight) return normalizedLeft - normalizedRight
  return left.order - right.order
}

function messageHasDisplayParts(message: TranscriptItem): boolean {
  return conversationVisibleParts(message.parts).some(partHasDisplayContent)
}

function messagePartsKey(message: TranscriptItem): string {
  return message.parts.map((part) => {
    if (part.type === 'text' || part.type === 'reasoning') {
      return `${part.id}:${part.status || ''}:${part.text.length}`
    }
    return `${part.id}:${part.type}:${part.status || ''}`
  }).join(',')
}

function partHasDisplayContent(part: ChatMessagePart): boolean {
  if (part.type === 'text' || part.type === 'reasoning') return part.text.trim().length > 0
  return ['tool_call', 'tool_result', 'attachment', 'artifact', 'error', 'status'].includes(part.type)
}

function isToolActivityRunning(tool: ToolActivity): boolean {
  return isToolActivityActive(tool)
}

function isKnowledgeRetrievalTool(tool: ToolActivity): boolean {
  const name = String(tool.toolName || '').toLowerCase()
  if (name !== 'knowledge') return false
  const action = String(tool.payload?.arguments?.action || '').toLowerCase()
  return !action || ['search', 'open', 'read', 'list_documents', 'describe_source', 'list_sources'].includes(action)
}
