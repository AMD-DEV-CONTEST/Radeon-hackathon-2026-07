import { BaseNode } from './BaseNode';
import type { WorkflowNodeData } from '../../../types/workflow';

interface RobotNodeProps {
  data: WorkflowNodeData;
  selected: boolean;
}

export function RobotNode({ data, selected }: RobotNodeProps) {
  return (
    <BaseNode data={data} selected={selected}>
      <div className="text-xs space-y-1 text-muted-foreground">
        <div className="flex justify-between">
          <span>Robot:</span>
          <span className="font-medium text-foreground">
            {data.config.robotId || 'Not selected'}
          </span>
        </div>
        {data.status === 'success' && (
          <div className="text-green-500 flex items-center gap-1">
            <span>✓</span>
            <span>Connected</span>
          </div>
        )}
      </div>
    </BaseNode>
  );
}
