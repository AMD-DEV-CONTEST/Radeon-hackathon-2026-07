import { BaseNode } from './BaseNode';
import type { WorkflowNodeData } from '../../../types/workflow';

interface Props {
  data: WorkflowNodeData;
  selected: boolean;
}

export function ReachyMoveOutputNode({ data, selected }: Props) {
  return (
    <BaseNode data={data} selected={selected}>
      <div className="text-xs space-y-1 text-muted-foreground">
        <div className="flex justify-between">
          <span>Output:</span>
          <span className="font-medium text-foreground">custom/*.json</span>
        </div>
        {data.status === 'success' && data.config._result && (
          <div className="mt-1 p-1.5 rounded bg-green-500/10 text-green-400 text-[10px] font-mono truncate">
            {(data.config._result as Record<string, unknown>).move_name as string}
          </div>
        )}
      </div>
    </BaseNode>
  );
}
