import { BaseNode } from './BaseNode';
import type { WorkflowNodeData } from '../../../types/workflow';

interface Props { data: WorkflowNodeData; selected: boolean; }

export function QualiaFinetuneNode({ data, selected }: Props) {
  const vlaType = (data.config.vlaType as string) || 'act';
  const hours = (data.config.hours as number) ?? 2;
  const gpu = (data.config.instanceType as string) || 'A100';

  return (
    <BaseNode data={data} selected={selected}>
      <div className="text-xs space-y-1 text-muted-foreground">
        <div className="flex justify-between">
          <span>Model:</span>
          <span className="font-medium text-foreground uppercase">{vlaType}</span>
        </div>
        <div className="flex justify-between">
          <span>GPU:</span>
          <span className="font-medium text-foreground">{gpu}</span>
        </div>
        <div className="flex justify-between">
          <span>Hours:</span>
          <span className="font-medium text-foreground">{hours}h</span>
        </div>
        <div className="flex justify-between">
          <span>Batch:</span>
          <span className="font-medium text-foreground">{(data.config.batchSize as number) ?? 32}</span>
        </div>
      </div>
    </BaseNode>
  );
}
