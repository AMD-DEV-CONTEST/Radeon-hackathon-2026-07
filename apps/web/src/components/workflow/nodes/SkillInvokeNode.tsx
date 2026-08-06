import { BaseNode } from './BaseNode';
import type { WorkflowNodeData } from '../../../types/workflow';

interface Props {
  data: WorkflowNodeData;
  selected: boolean;
}

export function SkillInvokeNode({ data, selected }: Props) {
  const skillId = (data.config.skillId as string) || '';
  const runtimeId = (data.config.runtimeId as string) || '';
  const paramCount = Object.keys((data.config.params as Record<string, unknown>) || {}).length;

  return (
    <BaseNode data={data} selected={selected}>
      <div className="text-xs space-y-1 text-muted-foreground">
        <div className="flex justify-between gap-2">
          <span>Skill:</span>
          <span className="font-medium text-foreground truncate max-w-[140px] font-mono text-[11px]">
            {skillId || 'Not set'}
          </span>
        </div>
        <div className="flex justify-between gap-2">
          <span>Runtime:</span>
          <span className="font-medium text-foreground truncate max-w-[140px]">
            {runtimeId || 'Not set'}
          </span>
        </div>
        {paramCount > 0 && (
          <div className="flex justify-between">
            <span>Params:</span>
            <span className="font-medium text-foreground">{paramCount}</span>
          </div>
        )}
      </div>
    </BaseNode>
  );
}
