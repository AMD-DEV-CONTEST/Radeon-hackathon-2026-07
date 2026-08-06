import { BaseNode } from './BaseNode';
import type { WorkflowNodeData } from '../../../types/workflow';

interface Props { data: WorkflowNodeData; selected: boolean; }

export function CameraNoiseNode({ data, selected }: Props) {
  const transforms = (data.config.transforms as string) || 'lighting,noise';
  const copies = (data.config.copies as number) ?? 3;
  const mode = (data.config.mode as string) || 'stacked';

  return (
    <BaseNode data={data} selected={selected}>
      <div className="text-xs space-y-1 text-muted-foreground">
        <div className="flex justify-between">
          <span>Transforms:</span>
          <span className="font-medium text-foreground">{transforms}</span>
        </div>
        <div className="flex justify-between">
          <span>Copies:</span>
          <span className="font-medium text-foreground">{copies}</span>
        </div>
        <div className="flex justify-between">
          <span>Mode:</span>
          <span className="font-medium text-foreground">{mode}</span>
        </div>
      </div>
    </BaseNode>
  );
}
