import type { Node, Edge, Connection } from '@xyflow/react';
import type {
  WorkflowNodeData,
  CameraMapEntry,
  VlaType,
  WorkflowValidationResult,
  PortDataType,
} from '../types/workflow';
import { nodeTemplates } from '../store/workflowStore';

export const SUPPORTED_VLA_TYPES: VlaType[] = [
  'act',
  'smolvla',
  'pi0',
  'pi05',
  'gr00t_n1_5',
  'gr00t_n1_6',
  'sarm',
  'wall_oss',
  'xvla',
];

export const SUPPORTED_INSTANCE_TYPES = ['A100', 'H100', 'A10G', 'L40S'];

/**
 * 校验单个节点的本地参数。
 * 返回空数组说明参数OK。
 */
export function validateNode(node: Node<WorkflowNodeData>): string[] {
  const errors: string[] = [];
  const { type, config } = node.data;

  switch (type) {
    case 'dataset_load':
    case 'hf_dataset': {
      const datasetId = (config.datasetId as string | undefined)?.trim();
      if (!datasetId) {
        errors.push('Dataset ID is required (e.g. lerobot/pusht)');
      } else if (!/^[\w.-]+\/[\w.-]+$/.test(datasetId)) {
        errors.push('Dataset ID should be in `owner/name` format');
      }
      break;
    }

    case 'camera_map': {
      const mappings = (config.mappings as CameraMapEntry[] | undefined) || [];
      if (mappings.length === 0) {
        errors.push('At least one camera mapping is required');
      } else {
        const filled = mappings.filter(
          (m) => m.slot && m.slot.trim() && m.imageKey && m.imageKey.trim()
        );
        if (filled.length === 0) {
          errors.push('At least one mapping must have both slot and image key');
        }
        const slots = filled.map((m) => m.slot.trim());
        const dupes = slots.filter((s, i) => slots.indexOf(s) !== i);
        if (dupes.length > 0) {
          errors.push(`Duplicate camera slots: ${Array.from(new Set(dupes)).join(', ')}`);
        }
      }
      break;
    }

    case 'finetune_job':
    case 'qualia_finetune': {
      const vla = config.vlaType as string | undefined;
      if (!vla) {
        errors.push('VLA type is required');
      } else if (!SUPPORTED_VLA_TYPES.includes(vla as VlaType)) {
        errors.push(`Unsupported VLA type: ${vla}`);
      }
      const hours = config.hours as number | undefined;
      if (typeof hours !== 'number' || Number.isNaN(hours)) {
        errors.push('Hours is required');
      } else if (hours <= 0 || hours > 168) {
        errors.push('Hours must be in (0, 168]');
      }
      const batch = config.batchSize as number | undefined;
      if (batch !== undefined && (batch < 1 || batch > 512)) {
        errors.push('Batch size must be in [1, 512]');
      }
      break;
    }

    case 'skill_invoke': {
      const skillId = (config.skillId as string | undefined)?.trim();
      const runtimeId = (config.runtimeId as string | undefined)?.trim();
      if (!skillId) errors.push('Skill is required');
      if (!runtimeId) errors.push('Runtime is required');
      break;
    }

    case 'job_monitor': {
      const interval = config.pollIntervalSec as number | undefined;
      if (interval !== undefined && interval < 1) {
        errors.push('Poll interval must be >= 1 second');
      }
      const timeout = config.timeoutMin as number | undefined;
      if (timeout !== undefined && timeout <= 0) {
        errors.push('Timeout must be > 0 minutes');
      }
      break;
    }

    default:
      break;
  }

  return errors;
}

/** 通过端口 id 反查端口类型 */
export function getPortType(
  node: Node<WorkflowNodeData>,
  portId: string | null | undefined,
  side: 'input' | 'output'
): PortDataType | null {
  if (!portId) return null;
  const ports = side === 'input' ? node.data.inputs : node.data.outputs;
  const port = ports.find((p) => p.id === portId);
  return port ? port.type : null;
}

/**
 * 端口兼容性判断。
 * any 与所有类型兼容；否则必须完全相等。
 */
export function arePortsCompatible(sourceType: PortDataType, targetType: PortDataType): boolean {
  if (sourceType === 'any' || targetType === 'any') return true;
  return sourceType === targetType;
}

/**
 * 判断一条新连线是否合法（端口类型、自连、重复）。
 * 返回 null 表示允许；否则返回错误信息。
 */
export function checkConnection(
  connection: Connection,
  nodes: Node<WorkflowNodeData>[],
  edges: Edge[]
): string | null {
  if (!connection.source || !connection.target) {
    return 'Invalid connection: missing endpoints';
  }
  if (connection.source === connection.target) {
    return 'Cannot connect a node to itself';
  }

  const sourceNode = nodes.find((n) => n.id === connection.source);
  const targetNode = nodes.find((n) => n.id === connection.target);
  if (!sourceNode || !targetNode) {
    return 'Source or target node not found';
  }

  const sourceType = getPortType(sourceNode, connection.sourceHandle, 'output');
  const targetType = getPortType(targetNode, connection.targetHandle, 'input');

  if (!sourceType || !targetType) {
    return 'Port definition missing';
  }

  if (!arePortsCompatible(sourceType, targetType)) {
    return `Port type mismatch: ${sourceType} → ${targetType}`;
  }

  // 防止重复连接同一对端口
  const dup = edges.some(
    (e) =>
      e.source === connection.source &&
      e.target === connection.target &&
      e.sourceHandle === connection.sourceHandle &&
      e.targetHandle === connection.targetHandle
  );
  if (dup) {
    return 'Duplicate connection';
  }

  return null;
}

/** 检查图是否存在环 */
function hasCycle(nodes: Node<WorkflowNodeData>[], edges: Edge[]): boolean {
  const graph = new Map<string, string[]>();
  nodes.forEach((n) => graph.set(n.id, []));
  edges.forEach((e) => {
    const arr = graph.get(e.source) || [];
    arr.push(e.target);
    graph.set(e.source, arr);
  });

  const WHITE = 0,
    GRAY = 1,
    BLACK = 2;
  const color = new Map<string, number>();
  nodes.forEach((n) => color.set(n.id, WHITE));

  const dfs = (id: string): boolean => {
    color.set(id, GRAY);
    const neighbors = graph.get(id) || [];
    for (const next of neighbors) {
      const c = color.get(next);
      if (c === GRAY) return true;
      if (c === WHITE && dfs(next)) return true;
    }
    color.set(id, BLACK);
    return false;
  };

  for (const n of nodes) {
    if (color.get(n.id) === WHITE && dfs(n.id)) return true;
  }
  return false;
}

/**
 * 运行前 workflow 级校验：
 * - 至少有一个节点
 * - 每个 required 输入端口都已连上
 * - 每个节点的本地参数校验通过
 * - Finetune 主链完整性（如包含 finetune_job，则需要 dataset_load & camera_map 连通）
 * - 无环
 */
export function validateWorkflow(
  nodes: Node<WorkflowNodeData>[],
  edges: Edge[]
): WorkflowValidationResult {
  const result: WorkflowValidationResult = {
    ok: true,
    errors: [],
    nodeErrors: [],
  };

  if (nodes.length === 0) {
    result.ok = false;
    result.errors.push('Workflow is empty');
    return result;
  }

  if (hasCycle(nodes, edges)) {
    result.ok = false;
    result.errors.push('Workflow contains a cycle');
  }

  // Per-node param validation
  for (const n of nodes) {
    const errs = validateNode(n);
    if (errs.length > 0) {
      result.nodeErrors.push({ nodeId: n.id, errors: errs });
    }
  }

  // Required input ports must be connected
  for (const n of nodes) {
    for (const input of n.data.inputs) {
      if (!input.required) continue;
      const connected = edges.some(
        (e) => e.target === n.id && e.targetHandle === input.id
      );
      if (!connected) {
        const existing = result.nodeErrors.find((ne) => ne.nodeId === n.id);
        const msg = `Input "${input.name}" is required but not connected`;
        if (existing) existing.errors.push(msg);
        else result.nodeErrors.push({ nodeId: n.id, errors: [msg] });
      }
    }
  }

  // Legacy finetune_job: requires dataset + camera_map
  const legacyFinetuneNodes = nodes.filter((n) => n.data.type === 'finetune_job');
  for (const ft of legacyFinetuneNodes) {
    const datasetEdge = edges.find(
      (e) => e.target === ft.id && e.targetHandle === 'dataset'
    );
    const mapEdge = edges.find(
      (e) => e.target === ft.id && e.targetHandle === 'mapping'
    );
    if (!datasetEdge) {
      result.errors.push(`Finetune node "${ft.data.label}" is missing an upstream dataset`);
    }
    if (!mapEdge) {
      result.errors.push(`Finetune node "${ft.data.label}" is missing an upstream camera mapping`);
    }
  }

  // Qualia finetune: dataset only (camera mappings live in node config)
  const qualiaFinetuneNodes = nodes.filter((n) => n.data.type === 'qualia_finetune');
  for (const ft of qualiaFinetuneNodes) {
    const datasetEdge = edges.find(
      (e) => e.target === ft.id && e.targetHandle === 'dataset'
    );
    if (!datasetEdge) {
      result.errors.push(`Finetune node "${ft.data.label}" is missing an upstream dataset`);
    }
  }

  if (result.errors.length > 0 || result.nodeErrors.length > 0) {
    result.ok = false;
  }

  return result;
}

/**
 * 通过 type 查找 template（用于兼容性/默认值）。
 */
export function findNodeTemplate(type: string) {
  return nodeTemplates.find((t) => t.type === type);
}
