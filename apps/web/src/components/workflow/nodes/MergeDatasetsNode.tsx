import { BaseNode } from './BaseNode';
import type { WorkflowNodeData } from '../../../types/workflow';

interface Props { data: WorkflowNodeData; selected: boolean; }

export function MergeDatasetsNode({ data, selected }: Props) {
  const inputCount = data.inputs.filter((p) => p.type === 'dataset').length;
  return (
    <BaseNode data={data} selected={selected}>
      <div className="text-xs space-y-1 text-muted-foreground">
        <div className="flex justify-between">
          <span>Inputs:</span>
          <span className="font-medium text-foreground">{inputCount} datasets</span>
        </div>
      </div>
    </BaseNode>
  );
}
