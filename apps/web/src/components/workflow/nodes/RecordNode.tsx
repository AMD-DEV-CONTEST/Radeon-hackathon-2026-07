import { BaseNode } from './BaseNode';
import type { WorkflowNodeData } from '../../../types/workflow';

interface RecordNodeProps {
  data: WorkflowNodeData;
  selected: boolean;
}

export function RecordNode({ data, selected }: RecordNodeProps) {
  return (
    <BaseNode data={data} selected={selected}>
      <div className="text-xs space-y-1 text-muted-foreground">
        <div className="flex justify-between">
          <span>Episodes:</span>
          <span className="font-medium text-foreground">
            {data.config.episodes || 10}
          </span>
        </div>
        <div className="flex justify-between">
          <span>FPS:</span>
          <span className="font-medium text-foreground">
            {data.config.fps || 30}
          </span>
        </div>
        {data.status === 'success' && data.config.datasetName && (
          <div className="text-green-500 mt-2 pt-2 border-t border-dashed">
            <div className="flex items-center gap-1">
              <span>✓</span>
              <span className="truncate">{data.config.datasetName}</span>
            </div>
          </div>
        )}
      </div>
    </BaseNode>
  );
}
