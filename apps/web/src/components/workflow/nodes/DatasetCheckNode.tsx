import { BaseNode } from './BaseNode';
import type { WorkflowNodeData } from '../../../types/workflow';

interface Props {
  data: WorkflowNodeData;
  selected: boolean;
}

export function DatasetCheckNode({ data, selected }: Props) {
  const repoId = (data.config.repoId as string) || '';

  return (
    <BaseNode data={data} selected={selected}>
      <div className="text-xs space-y-1 text-muted-foreground">
        <div className="flex justify-between gap-2">
          <span>Repo:</span>
          <span className="font-medium text-foreground truncate max-w-[140px] font-mono text-[10px]">
            {repoId || 'auto'}
          </span>
        </div>
        {data.status === 'success' && (
          <div className="mt-1 p-1.5 rounded bg-green-500/10 text-green-400 text-[10px]">
            Dataset validated
          </div>
        )}
      </div>
    </BaseNode>
  );
}
