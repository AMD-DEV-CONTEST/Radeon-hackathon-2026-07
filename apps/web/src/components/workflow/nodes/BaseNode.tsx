import React from 'react';
import { Handle, Position, useNodeId } from '@xyflow/react';
import { cn } from '../../../lib/utils';
import type { WorkflowNodeData, PortDataType } from '../../../types/workflow';
import { useWorkflowStore } from '../../../store/workflowStore';
import { arePortsCompatible } from '../../../lib/workflowValidation';

interface BaseNodeProps {
  data: WorkflowNodeData;
  selected: boolean;
  children: React.ReactNode;
}

function handleConnectStyle(
  nodeId: string,
  portId: string,
  side: 'input' | 'output',
  portType: PortDataType,
  connectingFrom: ReturnType<typeof useWorkflowStore.getState>['connectingFrom']
): React.CSSProperties | undefined {
  if (!connectingFrom) return undefined;
  if (connectingFrom.nodeId === nodeId && connectingFrom.handleId === portId) return undefined;

  if (connectingFrom.handleType === 'source') {
    if (side !== 'input') return { opacity: 0.35 };
    const ok = arePortsCompatible(connectingFrom.portType, portType);
    return ok
      ? { boxShadow: '0 0 0 3px rgba(34,197,94,0.6)', background: '#22c55e' }
      : { opacity: 0.25 };
  }
  if (side !== 'output') return { opacity: 0.35 };
  const ok = arePortsCompatible(portType, connectingFrom.portType);
  return ok
    ? { boxShadow: '0 0 0 3px rgba(34,197,94,0.6)', background: '#22c55e' }
    : { opacity: 0.25 };
}

export function BaseNode({ data, selected, children }: BaseNodeProps) {
  const nodeId = useNodeId() ?? '';
  const connectingFrom = useWorkflowStore((s) => s.connectingFrom);

  const statusStyles: Record<string, string> = {
    idle: '',
    running: 'ring-2 ring-yellow-500 shadow-lg shadow-yellow-500/20',
    success: 'ring-2 ring-green-500 shadow-lg shadow-green-500/20',
    error: 'ring-2 ring-red-500 shadow-lg shadow-red-500/20',
    api_pending: 'ring-2 ring-orange-400 shadow-lg shadow-orange-400/20',
  };

  return (
    <div
      className={cn(
        'min-w-[200px] rounded-xl border bg-card shadow-sm overflow-hidden',
        'transition-all duration-200',
        selected && 'ring-2 ring-primary',
        statusStyles[data.status]
      )}
      style={{ borderLeft: `4px solid ${data.color}` }}
    >
      {/* Header */}
      <div
        className="flex items-center gap-2 px-3 py-2 border-b"
        style={{ backgroundColor: `${data.color}10` }}
      >
        <span className="text-xl">{data.icon}</span>
        <div className="flex-1 min-w-0">
          <div className="font-medium text-sm truncate">{data.label}</div>
          <div className="text-xs text-muted-foreground truncate">
            {data.description}
          </div>
        </div>
        {/* Status indicator */}
        {data.status === 'running' && (
          <div className="w-2 h-2 rounded-full bg-yellow-500 animate-pulse" />
        )}
        {data.status === 'success' && (
          <div className="w-2 h-2 rounded-full bg-green-500" />
        )}
        {data.status === 'error' && (
          <div className="w-2 h-2 rounded-full bg-red-500" />
        )}
        {data.status === 'api_pending' && (
          <div className="w-2 h-2 rounded-full bg-orange-400" />
        )}
      </div>

      {/* Content */}
      <div className="p-3">
        {children}

        {/* Progress Bar */}
        {data.status === 'running' && data.progress !== undefined && (
          <div className="mt-3">
            <div className="flex justify-between text-xs text-muted-foreground mb-1">
              <span>Progress</span>
              <span>{data.progress}%</span>
            </div>
            <div className="h-2 bg-muted rounded-full overflow-hidden">
              <div
                className="h-full transition-all duration-300 ease-out rounded-full"
                style={{
                  width: `${data.progress}%`,
                  backgroundColor: data.color,
                }}
              />
            </div>
          </div>
        )}
      </div>

      {/* Input Handles */}
      {data.inputs.map((input, index) => (
        <Handle
          key={input.id}
          type="target"
          position={Position.Left}
          id={input.id}
          style={{
            top: `${((index + 1) / (data.inputs.length + 1)) * 100}%`,
            background: '#64748b',
            width: '10px',
            height: '10px',
            ...handleConnectStyle(nodeId, input.id, 'input', input.type, connectingFrom),
          }}
        />
      ))}

      {/* Output Handles */}
      {data.outputs.map((output, index) => (
        <Handle
          key={output.id}
          type="source"
          position={Position.Right}
          id={output.id}
          style={{
            top: `${((index + 1) / (data.outputs.length + 1)) * 100}%`,
            background: data.color,
            width: '10px',
            height: '10px',
            ...handleConnectStyle(nodeId, output.id, 'output', output.type, connectingFrom),
          }}
        />
      ))}
    </div>
  );
}
