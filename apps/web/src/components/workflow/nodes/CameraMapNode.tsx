import { BaseNode } from './BaseNode';
import type { WorkflowNodeData, CameraMapEntry } from '../../../types/workflow';

interface CameraMapNodeProps {
  data: WorkflowNodeData;
  selected: boolean;
}

export function CameraMapNode({ data, selected }: CameraMapNodeProps) {
  const mappings = (data.config.mappings as CameraMapEntry[]) || [];
  const filled = mappings.filter((m) => m.slot && m.imageKey);

  return (
    <BaseNode data={data} selected={selected}>
      <div className="text-xs space-y-1 text-muted-foreground">
        <div className="flex justify-between">
          <span>Mappings:</span>
          <span className="font-medium text-foreground">
            {filled.length}/{mappings.length || 1}
          </span>
        </div>
        {filled.slice(0, 3).map((m, i) => (
          <div key={i} className="flex justify-between gap-2">
            <span className="truncate max-w-[70px]">{m.slot}</span>
            <span className="text-foreground truncate max-w-[120px]">{m.imageKey}</span>
          </div>
        ))}
        {filled.length > 3 && (
          <div className="text-[10px] italic">+{filled.length - 3} more…</div>
        )}
      </div>
    </BaseNode>
  );
}
