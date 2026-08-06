import { BaseNode } from './BaseNode';
import type { WorkflowNodeData } from '../../../types/workflow';

interface Props { data: WorkflowNodeData; selected: boolean; }

export function OutputDatasetNode({ data, selected }: Props) {
  return (
    <BaseNode data={data} selected={selected}>
      <div className="text-xs space-y-1 text-muted-foreground">
        <div className="flex justify-between gap-2">
          <span>Name:</span>
          <span className="font-medium text-foreground truncate max-w-[140px]">
            {(data.config.outputName as string) || 'auto'}
          </span>
        </div>
        <div className="flex justify-between">
          <span>Mode:</span>
          <span className="font-medium text-foreground">
            {(data.config.datasetMode as string) || 'copy'}
          </span>
        </div>
      </div>
    </BaseNode>
  );
}
