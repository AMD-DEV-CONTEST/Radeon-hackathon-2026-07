/**
 * M24 — Reachy action nodes for the Workflow Editor.
 *
 * Adds four building blocks so users can compose Reachy behavior flows:
 *
 *   * ReachyPlayMoveNode       — play an official HF recorded move (emotions/dances)
 *   * ReachyEmotionNode        — alias pinned to the emotions library (quick-pick)
 *   * ReachyStartConversationNode — start the official Conversation App w/ backend choice
 *   * ReachyStopAppNode        — stop whatever App is currently running
 *
 * These are visual components only; execution lives in
 * `apps/web/src/lib/workflowEngine.ts` under the corresponding `case`
 * clauses.
 */
import { MessageSquare, Music4, Smile, Square } from 'lucide-react'
import { BaseNode } from './BaseNode'
import type { WorkflowNodeData } from '../../../types/workflow'

interface NodeProps {
  data: WorkflowNodeData
  selected: boolean
}

const EMOTION_LABELS: Record<string, string> = {
  happy: 'happy', cheerful: 'cheerful', laughing: 'laughing', proud: 'proud',
  sad: 'sad', lonely: 'lonely', downcast: 'downcast', boredom: 'boredom',
  angry: 'rage', rage: 'rage', irritated: 'irritated', furious: 'furious',
  surprised: 'surprised', amazed: 'amazed', curious: 'curious',
  grateful: 'grateful', relieved: 'relief', welcoming: 'welcoming',
  shy: 'shy', frustrated: 'frustrated', anxious: 'anxiety', resigned: 'resigned',
}

export function ReachyPlayMoveNode({ data, selected }: NodeProps) {
  const datasetKind = (data.config.datasetKind as string) || 'emotions'
  const moveName = (data.config.moveName as string) || ''
  return (
    <BaseNode data={data} selected={selected} icon={<Music4 className="h-4 w-4" />}>
      <div className="text-xs space-y-1 text-muted-foreground">
        <div className="flex justify-between gap-2">
          <span>库:</span>
          <span className="font-medium text-foreground">
            {datasetKind === 'emotions' ? '表情库' : '舞蹈库'}
          </span>
        </div>
        <div className="flex justify-between gap-2">
          <span>动作:</span>
          <span className="font-medium text-foreground truncate max-w-[120px]">
            {moveName || '(未选)'}
          </span>
        </div>
      </div>
    </BaseNode>
  )
}

export function ReachyEmotionNode({ data, selected }: NodeProps) {
  const emotion = (data.config.emotion as string) || ''
  return (
    <BaseNode data={data} selected={selected} icon={<Smile className="h-4 w-4" />}>
      <div className="text-xs space-y-1 text-muted-foreground">
        <div className="flex justify-between gap-2">
          <span>表情:</span>
          <span className="font-medium text-foreground truncate max-w-[120px]">
            {EMOTION_LABELS[emotion] || emotion || '(未选)'}
          </span>
        </div>
      </div>
    </BaseNode>
  )
}

export function ReachyStartConversationNode({ data, selected }: NodeProps) {
  const backend = (data.config.backend as string) || 'huggingface'
  const model = (data.config.model as string) || ''
  return (
    <BaseNode data={data} selected={selected} icon={<MessageSquare className="h-4 w-4" />}>
      <div className="text-xs space-y-1 text-muted-foreground">
        <div className="flex justify-between gap-2">
          <span>LLM:</span>
          <span className="font-medium text-foreground">{backend}</span>
        </div>
        {model && (
          <div className="flex justify-between gap-2">
            <span>模型:</span>
            <span className="font-medium text-foreground truncate max-w-[120px]">{model}</span>
          </div>
        )}
      </div>
    </BaseNode>
  )
}

export function ReachyStopAppNode({ data, selected }: NodeProps) {
  return (
    <BaseNode data={data} selected={selected} icon={<Square className="h-4 w-4" />}>
      <div className="text-xs text-muted-foreground">停止当前运行的 Reachy App</div>
    </BaseNode>
  )
}
