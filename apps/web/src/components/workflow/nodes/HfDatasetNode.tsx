import { BaseNode } from './BaseNode';
import type { WorkflowNodeData } from '../../../types/workflow';

interface Props { data: WorkflowNodeData; selected: boolean; }

export function HfDatasetNode({ data, selected }: Props) {
  const datasetId = (data.config.datasetId as string) || '';
  const imageKeys = (data.config.imageKeys as string[]) || [];

  return (
    <BaseNode data={data} selected={selected}>
      <div className="text-xs space-y-1 text-muted-foreground">
        <div className="flex justify-between gap-2">
          <span>Dataset:</span>
          <span className="font-medium text-foreground truncate max-w-[140px]">
            {datasetId || 'Not set'}
          </span>
        </div>
        <div className="flex justify-between">
          <span>Type:</span>
          <span className="font-medium text-foreground">
            {(data.config.datasetType as string) || 'lerobot_v3'}
          </span>
        </div>
        {imageKeys.length > 0 && (
          <div className="flex justify-between">
            <span>Image keys:</span>
            <span className="font-medium text-foreground">{imageKeys.length}</span>
          </div>
        )}
      </div>
    </BaseNode>
  );
}
