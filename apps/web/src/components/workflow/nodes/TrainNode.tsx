import { BaseNode } from './BaseNode';
import type { WorkflowNodeData } from '../../../types/workflow';

interface TrainNodeProps {
  data: WorkflowNodeData;
  selected: boolean;
}

export function TrainNode({ data, selected }: TrainNodeProps) {
  const modelTypeLabels: Record<string, string> = {
    act: 'ACT',
    diffusion: 'Diffusion',
    vla: 'VLA',
  };

  return (
    <BaseNode data={data} selected={selected}>
      <div className="text-xs space-y-1 text-muted-foreground">
        <div className="flex justify-between">
          <span>Model:</span>
          <span className="font-medium text-foreground">
            {modelTypeLabels[data.config.modelType] || 'ACT'}
          </span>
        </div>
        <div className="flex justify-between">
          <span>Epochs:</span>
          <span className="font-medium text-foreground">
            {data.config.epochs || 100}
          </span>
        </div>
        <div className="flex justify-between">
          <span>Batch:</span>
          <span className="font-medium text-foreground">
            {data.config.batchSize || 8}
          </span>
        </div>
        {data.status === 'running' && data.progress !== undefined && (
          <div className="mt-2 pt-2 border-t border-dashed text-amber-500">
            Epoch {Math.floor((data.progress / 100) * (data.config.epochs || 100))}/{data.config.epochs || 100}
          </div>
        )}
      </div>
    </BaseNode>
  );
}
