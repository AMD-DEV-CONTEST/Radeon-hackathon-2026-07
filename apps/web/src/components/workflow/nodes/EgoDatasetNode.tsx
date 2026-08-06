import { BaseNode } from './BaseNode';
import type { WorkflowNodeData } from '../../../types/workflow';

interface Props { data: WorkflowNodeData; selected: boolean; }

export function EgoDatasetNode({ data, selected }: Props) {
  return (
    <BaseNode data={data} selected={selected}>
      <div className="text-xs space-y-1 text-muted-foreground">
        <div className="flex justify-between gap-2">
          <span>Source:</span>
          <span className="font-medium text-foreground truncate max-w-[140px]">
            {(data.config.source as string) || 'Not set'}
          </span>
        </div>
        {(data.config.prompt as string) && (
          <div className="text-[10px] italic truncate">
            {data.config.prompt as string}
          </div>
        )}
      </div>
    </BaseNode>
  );
}
