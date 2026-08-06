import type { Edge, Node } from '@xyflow/react';
import type { WorkflowNodeData } from '../types/workflow';

/** Collect node id and all downstream nodes reachable via outgoing edges. */
export function getDownstreamSubgraph(
  startNodeId: string,
  nodes: Node<WorkflowNodeData>[],
  edges: Edge[]
): { nodes: Node<WorkflowNodeData>[]; edges: Edge[] } {
  const nodeIds = new Set<string>([startNodeId]);
  const queue = [startNodeId];

  while (queue.length > 0) {
    const id = queue.shift()!;
    for (const e of edges) {
      if (e.source === id && !nodeIds.has(e.target)) {
        nodeIds.add(e.target);
        queue.push(e.target);
      }
    }
  }

  const subNodes = nodes.filter((n) => nodeIds.has(n.id));
  const subEdges = edges.filter(
    (e) => nodeIds.has(e.source) && nodeIds.has(e.target)
  );
  return { nodes: subNodes, edges: subEdges };
}
