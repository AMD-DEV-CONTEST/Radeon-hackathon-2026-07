import { BaseEdge, getBezierPath, type EdgeProps } from '@xyflow/react';

export type EdgeRunStatus = 'idle' | 'active' | 'completed';

export interface AnimatedEdgeData {
  runStatus?: EdgeRunStatus;
  [key: string]: unknown;
}

export function AnimatedEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  style,
  markerEnd,
  data,
}: EdgeProps) {
  const runStatus = (data as AnimatedEdgeData | undefined)?.runStatus ?? 'idle';
  const [edgePath] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  });

  const stroke =
    runStatus === 'completed'
      ? '#22c55e'
      : runStatus === 'active'
        ? '#eab308'
        : (style?.stroke as string) ?? '#b1b1b7';

  const strokeWidth = runStatus === 'active' ? 2.5 : 2;

  return (
    <>
      <BaseEdge
        id={id}
        path={edgePath}
        markerEnd={markerEnd}
        style={{
          ...style,
          stroke,
          strokeWidth,
          strokeDasharray: runStatus === 'active' ? '8 4' : undefined,
          animation: runStatus === 'active' ? 'workflow-edge-flow 0.8s linear infinite' : undefined,
        }}
      />
      <style>{`
        @keyframes workflow-edge-flow {
          to { stroke-dashoffset: -24; }
        }
      `}</style>
    </>
  );
}
