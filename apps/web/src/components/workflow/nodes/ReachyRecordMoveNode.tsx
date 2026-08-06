import { BaseNode } from './BaseNode';
import type { WorkflowNodeData } from '../../../types/workflow';

interface Props {
  data: WorkflowNodeData;
  selected: boolean;
}

export function ReachyRecordMoveNode({ data, selected }: Props) {
  const moveName = (data.config.moveName as string) || '';
  const durationS = (data.config.durationS as number) ?? 10;
  const sampleHz = (data.config.sampleHz as number) ?? 100;

  return (
    <BaseNode data={data} selected={selected}>
      <div className="text-xs space-y-1 text-muted-foreground">
        <div className="flex justify-between gap-2">
          <span>Move:</span>
          <span className="font-medium text-foreground truncate max-w-[120px]">
            {moveName || 'auto'}
          </span>
        </div>
        <div className="flex justify-between">
          <span>Duration:</span>
          <span className="font-medium text-foreground">{durationS}s</span>
        </div>
        <div className="flex justify-between">
          <span>Sample Hz:</span>
          <span className="font-medium text-foreground">{sampleHz}</span>
        </div>
      </div>
    </BaseNode>
  );
}
