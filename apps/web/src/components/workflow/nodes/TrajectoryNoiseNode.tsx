import { BaseNode } from './BaseNode';
import type { WorkflowNodeData } from '../../../types/workflow';

interface Props { data: WorkflowNodeData; selected: boolean; }

export function TrajectoryNoiseNode({ data, selected }: Props) {
  const strength = (data.config.strength as number) ?? 0.1;

  return (
    <BaseNode data={data} selected={selected}>
      <div className="text-xs space-y-1 text-muted-foreground">
        <div className="flex justify-between">
          <span>Strength:</span>
          <span className="font-medium text-foreground">{strength}</span>
        </div>
        <div className="flex justify-between">
          <span>Joint noise:</span>
          <span className="font-medium text-foreground">{data.config.jointNoise ? 'Yes' : 'No'}</span>
        </div>
        <div className="flex justify-between">
          <span>Timestamp jitter:</span>
          <span className="font-medium text-foreground">{data.config.timestampJitter ? 'Yes' : 'No'}</span>
        </div>
      </div>
    </BaseNode>
  );
}
