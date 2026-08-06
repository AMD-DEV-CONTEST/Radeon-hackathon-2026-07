import { BaseNode } from './BaseNode';
import type { WorkflowNodeData } from '../../../types/workflow';

interface Props {
  data: WorkflowNodeData;
  selected: boolean;
}

export function ReachyDaemonCheckNode({ data, selected }: Props) {
  return (
    <BaseNode data={data} selected={selected}>
      <div className="text-xs space-y-1 text-muted-foreground">
        <div className="flex justify-between">
          <span>Target:</span>
          <span className="font-medium text-foreground">Reachy Mini</span>
        </div>
        {data.status === 'success' && (
          <div className="mt-1 p-1.5 rounded bg-green-500/10 text-green-400 text-[10px]">
            Daemon ready
          </div>
        )}
        {data.status === 'error' && (
          <div className="mt-1 p-1.5 rounded bg-red-500/10 text-red-400 text-[10px]">
            Daemon offline — start via Setup
          </div>
        )}
      </div>
    </BaseNode>
  );
}
