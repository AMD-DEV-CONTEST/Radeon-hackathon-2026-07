import { BaseNode } from './BaseNode';
import type { WorkflowNodeData } from '../../../types/workflow';

interface DeployNodeProps {
  data: WorkflowNodeData;
  selected: boolean;
}

export function DeployNode({ data, selected }: DeployNodeProps) {
  return (
    <BaseNode data={data} selected={selected}>
      <div className="text-xs space-y-1 text-muted-foreground">
        <div className="text-center py-2">
          {data.status === 'idle' && (
            <span>Ready to deploy</span>
          )}
          {data.status === 'running' && (
            <span className="text-amber-500">Deploying...</span>
          )}
          {data.status === 'success' && (
            <div className="text-green-500 flex items-center justify-center gap-1">
              <span>✓</span>
              <span>Running</span>
            </div>
          )}
          {data.status === 'error' && (
            <div className="text-red-500 flex items-center justify-center gap-1">
              <span>✗</span>
              <span>Failed</span>
            </div>
          )}
        </div>
      </div>
    </BaseNode>
  );
}
