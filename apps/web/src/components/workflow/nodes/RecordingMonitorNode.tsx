import { BaseNode } from './BaseNode';
import type { WorkflowNodeData } from '../../../types/workflow';

interface Props {
  data: WorkflowNodeData;
  selected: boolean;
}

export function RecordingMonitorNode({ data, selected }: Props) {
  const pollSec = (data.config.pollIntervalSec as number) ?? 3;

  return (
    <BaseNode data={data} selected={selected}>
      <div className="text-xs space-y-1 text-muted-foreground">
        <div className="flex justify-between">
          <span>Poll:</span>
          <span className="font-medium text-foreground">{pollSec}s</span>
        </div>
        {data.status === 'running' && data.logs && data.logs.length > 0 && (
          <div className="mt-1 p-1.5 rounded bg-yellow-500/10 text-yellow-300 text-[10px] font-mono truncate">
            {data.logs[data.logs.length - 1]}
          </div>
        )}
      </div>
    </BaseNode>
  );
}
