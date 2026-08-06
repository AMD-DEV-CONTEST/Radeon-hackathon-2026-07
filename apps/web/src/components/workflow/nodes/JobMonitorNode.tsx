import { BaseNode } from './BaseNode';
import type { WorkflowNodeData } from '../../../types/workflow';

interface JobMonitorNodeProps {
  data: WorkflowNodeData;
  selected: boolean;
}

export function JobMonitorNode({ data, selected }: JobMonitorNodeProps) {
  const interval = (data.config.pollIntervalSec as number) ?? 5;
  const timeout = (data.config.timeoutMin as number) ?? 60;

  return (
    <BaseNode data={data} selected={selected}>
      <div className="text-xs space-y-1 text-muted-foreground">
        <div className="flex justify-between">
          <span>Poll every:</span>
          <span className="font-medium text-foreground">{interval}s</span>
        </div>
        <div className="flex justify-between">
          <span>Timeout:</span>
          <span className="font-medium text-foreground">{timeout}min</span>
        </div>
        {data.status === 'running' && (
          <div className="mt-1 pt-1 border-t border-dashed text-emerald-500 flex items-center gap-1">
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
            <span>polling…</span>
          </div>
        )}
        {data.status === 'success' && (
          <div className="mt-1 pt-1 border-t border-dashed text-emerald-500">
            ✓ completed
          </div>
        )}
      </div>
    </BaseNode>
  );
}
