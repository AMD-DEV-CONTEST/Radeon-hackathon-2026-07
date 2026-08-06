import type {
  ChatMessagePart,
  ToolCallMessagePart,
  ToolExecutionMessagePart,
  ToolResultMessagePart,
} from '@/types/protocol'

export type ToolCategory =
  | 'read'
  | 'write'
  | 'search'
  | 'process'
  | 'knowledge'
  | 'scheduler'
  | 'agent'
  | 'extension'
  | 'generic'

export interface ToolPresentation {
  category: ToolCategory
  labelKey: string
  summary: string
}

const TOOL_PRESENTATIONS: Record<string, Pick<ToolPresentation, 'category' | 'labelKey'>> = {
  read: { category: 'read', labelKey: 'tool.names.read' },
  write: { category: 'write', labelKey: 'tool.names.write' },
  edit: { category: 'write', labelKey: 'tool.names.edit' },
  glob: { category: 'search', labelKey: 'tool.names.glob' },
  grep: { category: 'search', labelKey: 'tool.names.grep' },
  ls: { category: 'read', labelKey: 'tool.names.ls' },
  shell: { category: 'process', labelKey: 'tool.names.shell' },
  shell_status: { category: 'process', labelKey: 'tool.names.shellStatus' },
  shell_stop: { category: 'process', labelKey: 'tool.names.shellStop' },
  knowledge: { category: 'knowledge', labelKey: 'tool.names.knowledge' },
  scheduler: { category: 'scheduler', labelKey: 'tool.names.scheduler' },
  agent_list: { category: 'agent', labelKey: 'tool.names.agentList' },
  agent_search: { category: 'agent', labelKey: 'tool.names.agentSearch' },
  agent_manufacture: { category: 'agent', labelKey: 'tool.names.agentManufacture' },
  agent_delegate: { category: 'agent', labelKey: 'tool.names.agentDelegate' },
  agent_evolve: { category: 'agent', labelKey: 'tool.names.agentEvolve' },
  agent_team: { category: 'agent', labelKey: 'tool.names.agentTeam' },
  background_tasks: { category: 'agent', labelKey: 'backgroundTask.title' },
  skillhub: { category: 'extension', labelKey: 'tool.names.skillhub' },
  tool_output: { category: 'read', labelKey: 'tool.names.toolOutput' },
}

export function conversationVisibleParts(parts: ChatMessagePart[]): ChatMessagePart[] {
  return mergeToolMessageParts(parts)
}

export function toolPresentation(
  toolName: string,
  argumentsValue: unknown,
): ToolPresentation {
  const normalizedName = String(toolName || 'tool').trim()
  const configured = TOOL_PRESENTATIONS[normalizedName] || {
    category: 'generic' as const,
    labelKey: '',
  }
  return {
    ...configured,
    summary: toolArgumentSummary(normalizedName, argumentsValue),
  }
}

export function mergeToolMessageParts(parts: ChatMessagePart[]): ChatMessagePart[] {
  const merged: ChatMessagePart[] = []
  let activeExecution: ToolExecutionMessagePart | null = null

  for (const part of parts) {
    if (part.type === 'tool_call') {
      activeExecution = executionFromCall(part)
      merged.push(activeExecution)
      continue
    }
    if (part.type === 'tool_result') {
      const target = matchingExecution(merged, part)
      if (target) {
        target.output = part.output
        target.error = part.error
        target.status = part.status
        target.updatedAt = part.updatedAt
        activeExecution = target
      } else {
        activeExecution = executionFromResult(part)
        merged.push(activeExecution)
      }
      continue
    }
    if (part.type === 'artifact' && activeExecution) {
      activeExecution.artifacts.push(part)
      continue
    }
    activeExecution = null
    merged.push(part)
  }
  return merged
}

function executionFromCall(part: ToolCallMessagePart): ToolExecutionMessagePart {
  return {
    id: `${part.id}:execution`,
    type: 'tool_execution',
    toolName: part.toolName,
    callId: part.callId,
    arguments: part.arguments,
    output: part.liveOutput ?? null,
    approvalState: part.approvalState,
    artifacts: [],
    status: part.status,
    createdAt: part.createdAt,
    startedAt: part.startedAt,
    updatedAt: part.updatedAt,
  }
}

function executionFromResult(part: ToolResultMessagePart): ToolExecutionMessagePart {
  return {
    id: `${part.id}:execution`,
    type: 'tool_execution',
    toolName: part.toolName,
    callId: part.callId,
    arguments: {},
    output: part.output,
    error: part.error,
    artifacts: [],
    status: part.status,
    createdAt: part.createdAt,
    startedAt: part.startedAt,
    updatedAt: part.updatedAt,
  }
}

function matchingExecution(
  parts: ChatMessagePart[],
  result: ToolResultMessagePart,
): ToolExecutionMessagePart | null {
  for (let index = parts.length - 1; index >= 0; index -= 1) {
    const candidate = parts[index]
    if (candidate.type !== 'tool_execution') continue
    if (result.callId && candidate.callId === result.callId) return candidate
    if (!result.callId && candidate.toolName === result.toolName && candidate.output == null) return candidate
  }
  return null
}

function toolArgumentSummary(toolName: string, value: unknown): string {
  const args = recordValue(value)
  if (!args) return ''
  if (toolName === 'shell') return compact(args.command)
  if (toolName === 'grep') return compact(args.pattern, args.base_path)
  if (toolName === 'glob') return compact(args.pattern, args.base_path)
  if (toolName === 'edit') {
    const operations = Array.isArray(args.operations) ? args.operations : []
    const paths = operations
      .flatMap(operation => {
        const record = recordValue(operation)
        return record ? [record.path, record.source_path, record.destination_path] : []
      })
      .filter(Boolean)
      .slice(0, 2)
    return compact(args.action, ...paths, args.transaction_id)
  }
  if (toolName === 'read' || toolName === 'write' || toolName === 'ls') {
    return compact(args.path)
  }
  if (toolName === 'shell_status' || toolName === 'shell_stop') return compact(args.process_id)
  if (toolName === 'knowledge') return compact(args.action, args.query)
  if (toolName === 'scheduler') return compact(args.action, args.job_id)
  if (toolName === 'skillhub') return compact(args.action, args.query || args.slug)
  if (toolName.startsWith('agent_')) return compact(args.query, args.package_id || args.agent_id)
  return ''
}

function recordValue(value: unknown): Record<string, any> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, any>
    : null
}

function compact(...values: unknown[]): string {
  const text = values
    .map(value => String(value || '').replace(/\s+/g, ' ').trim())
    .filter(Boolean)
    .join(' · ')
  return text.length > 120 ? `${text.slice(0, 117)}...` : text
}
