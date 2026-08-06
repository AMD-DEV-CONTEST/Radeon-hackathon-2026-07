import type {
  ChatMessagePart,
  ChatMessagePartStatus,
  TranscriptAttachmentView,
  TranscriptItem,
  TranscriptReasoningView,
  ToolActivity,
} from '@/types/protocol'

export function textPart(
  id: string,
  text: string,
  options: {
    format?: 'markdown' | 'plain'
    status?: ChatMessagePartStatus
    timestamp?: string
  } = {},
): ChatMessagePart {
  return {
    id,
    type: 'text',
    format: options.format || 'markdown',
    text,
    status: options.status || 'completed',
    createdAt: options.timestamp,
    updatedAt: options.timestamp,
  }
}

export function reasoningPart(
  id: string,
  text: string,
  options: {
    status?: ChatMessagePartStatus
    timestamp?: string
  } = {},
): ChatMessagePart {
  return {
    id,
    type: 'reasoning',
    text,
    status: options.status || 'completed',
    createdAt: options.timestamp,
    updatedAt: options.timestamp,
  }
}

export function errorPart(id: string, message: string, details: unknown, timestamp: string): ChatMessagePart {
  return {
    id,
    type: 'error',
    message,
    details,
    status: 'failed',
    createdAt: timestamp,
    updatedAt: timestamp,
  }
}

export function attachmentPart(
  id: string,
  attachment: TranscriptAttachmentView,
  timestamp: string,
): ChatMessagePart {
  return {
    id,
    type: 'attachment',
    attachment,
    status: 'completed',
    createdAt: timestamp,
    updatedAt: timestamp,
  }
}

export function toolCallPart(tool: ToolActivity): ChatMessagePart {
  return {
    id: `${tool.activityKey}:call`,
    type: 'tool_call',
    toolName: tool.toolName,
    callId: tool.toolCallId,
    arguments: tool.payload?.arguments || tool.payload?.args || {},
    liveOutput: tool.payload?.output ?? null,
    approvalState: tool.approvalState,
    status: toolPartStatus(tool),
    createdAt: tool.createdAt,
    startedAt: tool.startedAt,
    updatedAt: tool.timestamp,
  }
}

export function toolResultPart(tool: ToolActivity): ChatMessagePart | null {
  if (!['completed', 'failed', 'cancelled', 'observed'].includes(tool.status)) return null
  return {
    id: `${tool.activityKey}:result`,
    type: 'tool_result',
    toolName: tool.toolName,
    callId: tool.toolCallId,
    output: tool.payload?.output || tool.payload?.result || tool.payload?.observation || tool.payload?.content || null,
    error: tool.payload?.error || null,
    status: tool.status === 'failed' ? 'failed' : tool.status === 'cancelled' ? 'cancelled' : 'completed',
    createdAt: tool.createdAt,
    startedAt: tool.startedAt,
    updatedAt: tool.timestamp,
  }
}

export function toolArtifactParts(tool: ToolActivity): ChatMessagePart[] {
  if (!['completed', 'observed'].includes(tool.status)) return []
  return artifactRecords(toolOutputValue(tool)).map((artifact, index) => ({
    id: `${tool.activityKey}:artifact:${index}`,
    type: 'artifact',
    name: artifactName(artifact),
    path: optionalText(artifact.relative_path || artifact.path),
    mimeType: optionalText(artifact.mime_type || artifact.mimeType),
    sizeBytes: optionalNumber(artifact.size_bytes ?? artifact.sizeBytes),
    status: 'completed',
    createdAt: tool.createdAt,
    updatedAt: tool.timestamp,
  }))
}

function toolOutputValue(tool: ToolActivity): unknown {
  return tool.payload?.output || tool.payload?.result || tool.payload?.observation || tool.payload?.content
}

function artifactRecords(value: unknown): Record<string, any>[] {
  let current = value
  for (let depth = 0; depth < 3; depth += 1) {
    if (!current || typeof current !== 'object' || Array.isArray(current)) return []
    const record = current as Record<string, any>
    const artifacts = Array.isArray(record.artifacts)
      ? record.artifacts
      : Array.isArray(record.assets)
        ? record.assets
        : null
    if (artifacts) {
      return artifacts.filter((item): item is Record<string, any> => Boolean(item && typeof item === 'object'))
    }
    current = record.output
  }
  return []
}

function artifactName(artifact: Record<string, any>): string {
  const explicit = optionalText(artifact.name)
  if (explicit) return explicit
  const path = optionalText(artifact.relative_path || artifact.path) || 'artifact'
  return path.replace(/\\/g, '/').split('/').pop() || 'artifact'
}

function optionalText(value: unknown): string | null {
  const text = typeof value === 'string' ? value.trim() : ''
  return text || null
}

function optionalNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

export function messageText(message: TranscriptItem): string {
  return message.parts
    .filter((part): part is Extract<ChatMessagePart, { type: 'text' }> => part.type === 'text')
    .map((part) => part.text)
    .join('')
}

export function messageReasoning(message: TranscriptItem): TranscriptReasoningView | undefined {
  const reasoning = message.parts.find(
    (part): part is Extract<ChatMessagePart, { type: 'reasoning' }> => part.type === 'reasoning',
  )
  if (!reasoning || !reasoning.text.trim()) return undefined
  return {
    content: reasoning.text,
    active: reasoning.status === 'streaming',
    completedAt: reasoning.status === 'streaming' ? null : reasoning.updatedAt || null,
  }
}

export function partsToText(parts: ChatMessagePart[]): string {
  return parts
    .filter((part): part is Extract<ChatMessagePart, { type: 'text' }> => part.type === 'text')
    .map((part) => part.text)
    .join('')
}

export function upsertPart(parts: ChatMessagePart[], nextPart: ChatMessagePart): ChatMessagePart[] {
  const index = parts.findIndex((part) => part.id === nextPart.id)
  if (index < 0) return [...parts, nextPart]
  const updated = [...parts]
  updated[index] = { ...updated[index], ...nextPart } as ChatMessagePart
  return updated
}

function toolPartStatus(tool: ToolActivity): ChatMessagePartStatus {
  if (tool.approvalState === 'approved') return 'completed'
  if (tool.approvalState === 'rejected' || tool.approvalState === 'denied') return 'failed'
  if (tool.status === 'approval') return 'awaiting_approval'
  if (tool.status === 'started' || tool.status === 'proposed') return 'running'
  if (tool.status === 'failed') return 'failed'
  if (tool.status === 'cancelled') return 'cancelled'
  return 'completed'
}
