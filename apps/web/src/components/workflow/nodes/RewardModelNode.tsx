import { BaseNode } from './BaseNode';
import type { WorkflowNodeData } from '../../../types/workflow';

interface Props { data: WorkflowNodeData; selected: boolean; }

export function RewardModelNode({ data, selected }: Props) {
  return (
    <BaseNode data={data} selected={selected}>
      <div className="text-xs space-y-1 text-muted-foreground">
        <div className="flex justify-between">
          <span>Head:</span>
          <span className="font-medium text-foreground">{(data.config.headMode as string) || 'dense'}</span>
        </div>
        <div className="flex justify-between">
          <span>GPU:</span>
          <span className="font-medium text-foreground">{(data.config.instanceType as string) || 'H100'}</span>
        </div>
        <div className="flex justify-between">
          <span>Hours:</span>
          <span className="font-medium text-foreground">{(data.config.hours as number) ?? 2}h</span>
        </div>
        <div className="px-2 py-1 mt-1 rounded bg-orange-500/10 border border-orange-500/20 text-orange-600 font-medium text-[10px]">
          API Pending
        </div>
      </div>
    </BaseNode>
  );
}
