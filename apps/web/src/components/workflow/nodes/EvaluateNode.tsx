import { BaseNode } from './BaseNode';
import type { WorkflowNodeData } from '../../../types/workflow';

interface Props {
  data: WorkflowNodeData;
  selected: boolean;
}

export function EvaluateNode({ data, selected }: Props) {
  const threshold = (data.config.passThreshold as number) ?? 0.7;
  const metrics = (data.config.metrics as string[]) ?? ['success_rate', 'loss'];

  return (
    <BaseNode data={data} selected={selected}>
      <div className="text-xs space-y-1 text-muted-foreground">
        <div className="flex justify-between">
          <span>Threshold:</span>
          <span className="font-medium text-foreground">{(threshold * 100).toFixed(0)}%</span>
        </div>
        <div className="flex justify-between">
          <span>Metrics:</span>
          <span className="font-medium text-foreground">{metrics.join(', ')}</span>
        </div>
        {data.status === 'success' && data.config._result && (
          <div className="mt-1 p-1.5 rounded bg-green-500/10 text-green-400 text-[10px]">
            Score: {String((data.config._result as Record<string, unknown>).score ?? '—')} · {(data.config._result as Record<string, unknown>).passed ? '✓ PASS' : '✗ FAIL'}
          </div>
        )}
      </div>
    </BaseNode>
  );
}
