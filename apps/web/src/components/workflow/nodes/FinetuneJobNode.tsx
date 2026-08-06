import { BaseNode } from './BaseNode';
import type { WorkflowNodeData } from '../../../types/workflow';

interface FinetuneJobNodeProps {
  data: WorkflowNodeData;
  selected: boolean;
}

export function FinetuneJobNode({ data, selected }: FinetuneJobNodeProps) {
  const vla = (data.config.vlaType as string) || 'act';
  const hours = (data.config.hours as number) ?? 2;
  const instance = (data.config.instanceType as string) || 'A100';
  const batch = (data.config.batchSize as number) ?? 32;
  const jobType = (data.config.jobType as string) || 'vla';

  return (
    <BaseNode data={data} selected={selected}>
      <div className="text-xs space-y-1 text-muted-foreground">
        <div className="flex justify-between">
          <span>VLA:</span>
          <span className="font-medium text-foreground uppercase">{vla}</span>
        </div>
        <div className="flex justify-between">
          <span>Hours:</span>
          <span className="font-medium text-foreground">{hours}h</span>
        </div>
        <div className="flex justify-between">
          <span>GPU:</span>
          <span className="font-medium text-foreground">{instance}</span>
        </div>
        <div className="flex justify-between">
          <span>Batch:</span>
          <span className="font-medium text-foreground">{batch}</span>
        </div>
        <div className="flex justify-between">
          <span>Type:</span>
          <span className="font-medium text-foreground">{jobType}</span>
        </div>
      </div>
    </BaseNode>
  );
}
