import { BaseNode } from './BaseNode';
import type { WorkflowNodeData } from '../../../types/workflow';

interface Props { data: WorkflowNodeData; selected: boolean; }

export function ApiPendingNode({ data, selected }: Props) {
  return (
    <BaseNode data={data} selected={selected}>
      <div className="text-xs space-y-1.5">
        <div className="px-2 py-1.5 rounded bg-orange-500/10 border border-orange-500/20 text-orange-600 font-medium">
          API Pending
        </div>
        <p className="text-muted-foreground text-[10px]">
          Qualia Studio node — BotverseX API integration pending.
        </p>
      </div>
    </BaseNode>
  );
}
