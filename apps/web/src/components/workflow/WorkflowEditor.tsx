import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  addEdge,
  ReactFlowProvider,
  useReactFlow,
} from '@xyflow/react';
import type { Connection, Edge, Node, OnConnectStartParams } from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import { NodePalette } from './NodePalette';
import { PropertiesPanel } from './PropertiesPanel';
import { ConsolePanel } from './ConsolePanel';
import { WorkflowEmptyState } from './WorkflowEmptyState';
import { AnimatedEdge } from './AnimatedEdge';
import { nodeTypes } from './nodes';
import { useWorkflowStore } from '../../store/workflowStore';
import { WorkflowEngine } from '../../lib/workflowEngine';
import {
  checkConnection,
  validateWorkflow,
  findNodeTemplate,
  getPortType,
} from '../../lib/workflowValidation';
import { getDownstreamSubgraph } from '../../lib/workflowSubgraph';
import type { WorkflowNodeData, NodeTemplate, ExecutionLog, NodeType } from '../../types/workflow';
import { Button } from '../ui/button';
import { Play, Pause, Save, FolderOpen, Download, Zap, CircleDot, Bot, Cpu, Copy, Trash2, PlayCircle, ScrollText } from 'lucide-react';
import { nodeTemplates } from '../../store/workflowStore';

const edgeTypes = { animated: AnimatedEdge, default: AnimatedEdge };

type WorkflowSnapshot = { nodes: Node<WorkflowNodeData>[]; edges: Edge[] };

function logEntry(level: ExecutionLog['level'], message: string): ExecutionLog {
  return {
    timestamp: new Date().toISOString(),
    nodeId: '',
    nodeType: 'finetune_job' as NodeType,
    level,
    message,
  };
}

// Inner component that has access to ReactFlow instance
function WorkflowEditorInner() {
  const {
    nodes,
    edges,
    setNodes,
    setEdges,
    onNodesChange,
    onEdgesChange,
    selectedNode,
    setSelectedNode,
    isRunning,
    setIsRunning,
    addExecutionLog,
    updateNodeStatus,
    resetExecutionState,
    removeNode,
    setConnectingFrom,
    setActiveRunningNodeId,
    markNodeCompleted,
    completedNodeIds,
    activeRunningNodeId,
    setConsoleExpanded,
    setConsoleFilterNodeId,
  } = useWorkflowStore();

  const { screenToFlowPosition, fitView } = useReactFlow();
  const engineRef = useRef<WorkflowEngine | null>(null);
  const undoStack = useRef<WorkflowSnapshot[]>([]);
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; nodeId: string } | null>(null);
  const [emptyHintDismissed, setEmptyHintDismissed] = useState(false);
  const [paletteDragOver, setPaletteDragOver] = useState(false);

  const pushUndo = useCallback(() => {
    undoStack.current.push({
      nodes: JSON.parse(JSON.stringify(nodes)) as Node<WorkflowNodeData>[],
      edges: JSON.parse(JSON.stringify(edges)) as Edge[],
    });
    if (undoStack.current.length > 40) undoStack.current.shift();
  }, [nodes, edges]);

  const onConnect = useCallback(
    (params: Connection) => {
      const err = checkConnection(params, nodes, edges);
      if (err) {
        addExecutionLog(logEntry('warn', `Connection rejected: ${err}`));
        return;
      }
      pushUndo();
      setEdges((eds) => addEdge(params, eds));
    },
    [nodes, edges, setEdges, addExecutionLog, pushUndo]
  );

  const onConnectStart = useCallback(
    (_: MouseEvent | TouchEvent, params: OnConnectStartParams) => {
      const node = nodes.find((n) => n.id === params.nodeId);
      if (!node || !params.handleId || !params.handleType) return;
      const side = params.handleType === 'source' ? 'output' : 'input';
      const portType = getPortType(node, params.handleId, side);
      if (!portType) return;
      setConnectingFrom({
        nodeId: params.nodeId,
        handleId: params.handleId,
        handleType: params.handleType,
        portType,
      });
    },
    [nodes, setConnectingFrom]
  );

  const onConnectEnd = useCallback(() => {
    setConnectingFrom(null);
  }, [setConnectingFrom]);

  const isValidConnection = useCallback(
    (conn: Connection | Edge) => {
      const connection: Connection = {
        source: (conn as Connection).source ?? null,
        target: (conn as Connection).target ?? null,
        sourceHandle: (conn as Connection).sourceHandle ?? null,
        targetHandle: (conn as Connection).targetHandle ?? null,
      };
      return checkConnection(connection, nodes, edges) === null;
    },
    [nodes, edges]
  );

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      setSelectedNode(node.id);
    },
    [setSelectedNode]
  );

  const onPaneClick = useCallback(() => {
    setSelectedNode(null);
    setContextMenu(null);
  }, [setSelectedNode]);

  const onNodeContextMenu = useCallback(
    (e: React.MouseEvent, node: Node) => {
      e.preventDefault();
      setContextMenu({ x: e.clientX, y: e.clientY, nodeId: node.id });
      setSelectedNode(node.id);
    },
    [setSelectedNode]
  );

  const duplicateNode = useCallback(
    (nodeId: string) => {
      const n = nodes.find((nd) => nd.id === nodeId);
      if (!n) return;
      pushUndo();
      const newId = `${n.data.type}_${Date.now()}`;
      const copy: Node<WorkflowNodeData> = {
        ...n,
        id: newId,
        position: { x: n.position.x + 48, y: n.position.y + 32 },
        data: { ...n.data, status: 'idle', progress: undefined },
      };
      setNodes((nds) => [...nds, copy]);
      setSelectedNode(newId);
      setContextMenu(null);
    },
    [nodes, pushUndo, setNodes, setSelectedNode]
  );

  const deleteSelectedNode = useCallback(() => {
    if (!selectedNode) return;
    pushUndo();
    removeNode(selectedNode);
    setContextMenu(null);
  }, [selectedNode, pushUndo, removeNode]);

  useEffect(() => {
    if (nodes.length > 0) {
      setEmptyHintDismissed(false);
      setPaletteDragOver(false);
    }
  }, [nodes.length]);

  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
    if (event.dataTransfer.types.includes('application/reactflow')) {
      setPaletteDragOver(true);
    }
  }, []);

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      setPaletteDragOver(false);

      const templateData = event.dataTransfer.getData('application/reactflow');
      if (!templateData) return;

      const template: NodeTemplate = JSON.parse(templateData);

      const position = screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      });

      const newId = `${template.type}_${Date.now()}`;
      const newNode: Node<WorkflowNodeData> = {
        id: newId,
        type: template.type,
        position,
        data: {
          label: template.label,
          type: template.type as WorkflowNodeData['type'],
          description: template.description,
          icon: template.icon,
          color: template.color,
          status: 'idle',
          config: { ...template.defaultConfig },
          inputs: template.inputs,
          outputs: template.outputs,
        },
      };

      pushUndo();
      setNodes((nds) => [...nds, newNode]);
      setSelectedNode(newId);
    },
    [screenToFlowPosition, setNodes, setSelectedNode, pushUndo]
  );

  const displayEdges = useMemo(() => {
    const showRunState = isRunning || completedNodeIds.length > 0;
    return edges.map((e) => {
      let runStatus: 'idle' | 'active' | 'completed' = 'idle';
      if (showRunState) {
        if (activeRunningNodeId && e.target === activeRunningNodeId) runStatus = 'active';
        else if (completedNodeIds.includes(e.source)) runStatus = 'completed';
      }
      return {
        ...e,
        type: 'animated',
        data: { ...e.data, runStatus },
      };
    });
  }, [edges, isRunning, activeRunningNodeId, completedNodeIds]);

  const executeWorkflow = async (
    runNodes: Node<WorkflowNodeData>[],
    runEdges: Edge[]
  ) => {
    const validation = validateWorkflow(runNodes, runEdges);
    if (!validation.ok) {
      addExecutionLog(logEntry('error', 'Preflight check failed — fix the issues below:'));
      validation.errors.forEach((e) => addExecutionLog(logEntry('error', `• ${e}`)));
      validation.nodeErrors.forEach((ne) => {
        const node = runNodes.find((n) => n.id === ne.nodeId);
        const label = node?.data.label || ne.nodeId;
        ne.errors.forEach((err) =>
          addExecutionLog(logEntry('error', `• [${label}] ${err}`))
        );
      });
      return;
    }

    resetExecutionState();
    setIsRunning(true);
    setConsoleExpanded(true);

    const engine = new WorkflowEngine(`workflow_${Date.now()}`);
    engineRef.current = engine;

    try {
      await engine.execute(runNodes, runEdges, {
        onNodeStart: (id) => {
          updateNodeStatus(id, 'running');
          setActiveRunningNodeId(id);
        },
        onNodeProgress: (id, progress) => {
          updateNodeStatus(id, 'running', progress);
        },
        onNodeComplete: (id, result) => {
          markNodeCompleted(id);
          setActiveRunningNodeId(null);
          updateNodeStatus(
            id,
            result?.status === 'api_pending' ? 'api_pending' : 'success'
          );
        },
        onNodeError: (id, error) => {
          setActiveRunningNodeId(null);
          updateNodeStatus(id, 'error');
          console.error(`Node ${id} error:`, error);
        },
        onLog: (log) => addExecutionLog(log),
      });
    } catch (error) {
      console.error('Workflow execution failed:', error);
    } finally {
      setIsRunning(false);
      setActiveRunningNodeId(null);
    }
  };

  const handleRun = async (subsetStartId?: string) => {
    if (isRunning) {
      engineRef.current?.stop();
      setIsRunning(false);
      setActiveRunningNodeId(null);
      return;
    }

    if (subsetStartId) {
      const sub = getDownstreamSubgraph(subsetStartId, nodes, edges);
      if (sub.nodes.length === 0) return;
      addExecutionLog(logEntry('info', `Run from node: ${subsetStartId}`));
      await executeWorkflow(sub.nodes, sub.edges);
      return;
    }

    await executeWorkflow(nodes, edges);
  };

  const handleSave = () => {
    const workflow = {
      schemaVersion: 2,
      nodes,
      edges,
      timestamp: new Date().toISOString(),
    };
    localStorage.setItem('botverse_workflow', JSON.stringify(workflow));
    addExecutionLog(logEntry('success', 'Workflow saved to local storage'));
  };

  const handleLoad = () => {
    const saved = localStorage.getItem('botverse_workflow');
    if (!saved) {
      addExecutionLog(logEntry('warn', 'No saved workflow found'));
      return;
    }
    try {
      const workflow = JSON.parse(saved);
      const loadedNodes: Node<WorkflowNodeData>[] = (workflow.nodes || [])
        .map((n: Node<WorkflowNodeData>) => reconcileNode(n))
        .filter(Boolean) as Node<WorkflowNodeData>[];
      const skipped = (workflow.nodes || []).length - loadedNodes.length;
      pushUndo();
      setNodes(loadedNodes);
      setEdges(workflow.edges || []);
      setSelectedNode(null);
      addExecutionLog(logEntry('success', 'Workflow loaded from local storage'));
      if (skipped > 0) {
        addExecutionLog(logEntry('warn', `${skipped} unknown node(s) were skipped`));
      }
    } catch (e) {
      addExecutionLog(logEntry('error', `Failed to load: ${(e as Error).message}`));
    }
  };

  const handleExport = () => {
    const workflow = {
      schemaVersion: 2,
      nodes,
      edges,
      timestamp: new Date().toISOString(),
    };
    const blob = new Blob([JSON.stringify(workflow, null, 2)], {
      type: 'application/json',
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `workflow_${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const loadDemoTemplate = (templateId: string) => {
    const tmpl = buildDemoTemplate(templateId);
    if (!tmpl) return;
    if (nodes.length > 0) pushUndo();
    setNodes(tmpl.nodes);
    setEdges(tmpl.edges);
    setSelectedNode(null);
    addExecutionLog(logEntry('success', `Loaded demo: ${tmpl.name}`));
    window.setTimeout(() => fitView({ padding: 0.15, duration: 300 }), 50);
  };

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      const inInput = tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';

      if (e.key === 'Escape') {
        setSelectedNode(null);
        setContextMenu(null);
        return;
      }

      if (inInput) return;

      if ((e.key === 'Delete' || e.key === 'Backspace') && selectedNode) {
        e.preventDefault();
        deleteSelectedNode();
        return;
      }

      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault();
        const workflow = {
          schemaVersion: 2,
          nodes,
          edges,
          timestamp: new Date().toISOString(),
        };
        localStorage.setItem('botverse_workflow', JSON.stringify(workflow));
        addExecutionLog(logEntry('success', 'Workflow saved to local storage'));
        return;
      }

      if ((e.ctrlKey || e.metaKey) && e.key === 'z') {
        e.preventDefault();
        const snap = undoStack.current.pop();
        if (snap) {
          setNodes(snap.nodes);
          setEdges(snap.edges);
          setSelectedNode(null);
          addExecutionLog(logEntry('info', 'Undo'));
        }
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [selectedNode, deleteSelectedNode, setSelectedNode, setNodes, setEdges, addExecutionLog, nodes, edges]);

  return (
    <div className="h-[calc(100vh-3.5rem)] flex flex-col -mx-4 -my-6">
      {/* Header */}
      <div className="h-14 border-b flex items-center justify-between px-4 bg-card shrink-0">
        <div className="flex items-center gap-3">
          <h1 className="text-lg font-semibold">Workflow Editor</h1>
          <span className="text-xs text-muted-foreground">
            Build your Qualia finetune pipeline
          </span>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={handleLoad}>
            <FolderOpen className="w-4 h-4 mr-1.5" />
            Load
          </Button>
          <Button variant="outline" size="sm" onClick={handleSave}>
            <Save className="w-4 h-4 mr-1.5" />
            Save
          </Button>
          <Button variant="outline" size="sm" onClick={handleExport}>
            <Download className="w-4 h-4 mr-1.5" />
            Export
          </Button>
          <div className="w-px h-6 bg-border mx-1" />
          <DemoTemplateMenu onSelect={loadDemoTemplate} />
          <div className="w-px h-6 bg-border mx-1" />
          <Button
            size="sm"
            onClick={() => handleRun()}
            disabled={nodes.length === 0}
            className={
              isRunning
                ? 'bg-yellow-600 hover:bg-yellow-700'
                : 'bg-primary hover:bg-primary/90'
            }
          >
            {isRunning ? (
              <>
                <Pause className="w-4 h-4 mr-1.5" />
                Stop
              </>
            ) : (
              <>
                <Play className="w-4 h-4 mr-1.5" />
                Run
              </>
            )}
          </Button>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 flex overflow-hidden">
        <NodePalette />

        <div className="flex-1 flex flex-col min-w-0">
          <div
            className="flex-1 relative"
            onDragLeave={(event) => {
              const related = event.relatedTarget as Node | null;
              if (related && event.currentTarget.contains(related)) return;
              setPaletteDragOver(false);
            }}
          >
            <ReactFlow
              nodes={nodes}
              edges={displayEdges}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onConnect={onConnect}
              onConnectStart={onConnectStart}
              onConnectEnd={onConnectEnd}
              isValidConnection={isValidConnection}
              onNodeClick={onNodeClick}
              onNodeContextMenu={onNodeContextMenu}
              onPaneClick={onPaneClick}
              onDragOver={onDragOver}
              onDrop={onDrop}
              nodeTypes={nodeTypes}
              edgeTypes={edgeTypes}
              connectionLineStyle={{ stroke: '#22c55e', strokeWidth: 2 }}
              fitView
              attributionPosition="bottom-left"
            >
              <Background gap={12} size={1} />
              <Controls />
              <MiniMap nodeStrokeWidth={3} zoomable pannable />
            </ReactFlow>
            {nodes.length === 0 && !emptyHintDismissed && !paletteDragOver && (
              <WorkflowEmptyState
                onLoadTemplate={loadDemoTemplate}
                onDismiss={() => setEmptyHintDismissed(true)}
              />
            )}
            {contextMenu && (
              <div
                className="fixed z-[100] min-w-[180px] py-1 rounded-lg border bg-card shadow-lg"
                style={{ left: contextMenu.x, top: contextMenu.y }}
                onClick={(e) => e.stopPropagation()}
              >
                <button
                  type="button"
                  className="w-full px-3 py-2 text-sm text-left hover:bg-muted flex items-center gap-2"
                  onClick={() => duplicateNode(contextMenu.nodeId)}
                >
                  <Copy className="w-4 h-4" /> 复制节点
                </button>
                <button
                  type="button"
                  className="w-full px-3 py-2 text-sm text-left hover:bg-muted flex items-center gap-2"
                  onClick={() => {
                    handleRun(contextMenu.nodeId);
                    setContextMenu(null);
                  }}
                >
                  <PlayCircle className="w-4 h-4" /> 从此节点运行
                </button>
                <button
                  type="button"
                  className="w-full px-3 py-2 text-sm text-left hover:bg-muted flex items-center gap-2"
                  onClick={() => {
                    setConsoleFilterNodeId(contextMenu.nodeId);
                    setConsoleExpanded(true);
                    setContextMenu(null);
                  }}
                >
                  <ScrollText className="w-4 h-4" /> 查看日志
                </button>
                <button
                  type="button"
                  className="w-full px-3 py-2 text-sm text-left hover:bg-muted text-red-500 flex items-center gap-2"
                  onClick={() => {
                    pushUndo();
                    removeNode(contextMenu.nodeId);
                    setContextMenu(null);
                    if (selectedNode === contextMenu.nodeId) setSelectedNode(null);
                  }}
                >
                  <Trash2 className="w-4 h-4" /> 删除
                </button>
              </div>
            )}
          </div>

          <ConsolePanel />
        </div>

        <PropertiesPanel selectedNode={selectedNode} />
      </div>
    </div>
  );
}

// ---------- Demo Template Menu ----------

function DemoTemplateMenu({ onSelect }: { onSelect: (id: string) => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as HTMLElement)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const templates = [
    { id: 'qualia-three-branch', label: 'Qualia 三链工作流', icon: <Zap className="w-3.5 h-3.5" />, desc: 'HF 增强 + World Model + URDF/IDM → Merge → Pi0.5 / Cosmos / Reward' },
    { id: 'skill-factory', label: 'Skill Factory', icon: <Zap className="w-3.5 h-3.5" />, desc: 'Dataset → Train → Evaluate → Publish Skill' },
    { id: 'so101-recording', label: 'SO-101 Recording', icon: <CircleDot className="w-3.5 h-3.5" />, desc: 'Real SO-101 dataset recording' },
    { id: 'reachy-recording', label: 'Reachy Recording', icon: <Bot className="w-3.5 h-3.5" />, desc: 'Real Reachy custom move recording' },
    { id: 'run-skill', label: 'Run Installed Skill', icon: <Cpu className="w-3.5 h-3.5" />, desc: 'Invoke an installed skill' },
  ];

  return (
    <div className="relative" ref={ref}>
      <Button variant="outline" size="sm" onClick={() => setOpen(!open)}>
        <Zap className="w-4 h-4 mr-1.5" />
        Demos
      </Button>
      {open && (
        <div className="absolute top-full right-0 mt-1 w-72 bg-card border rounded-lg shadow-lg z-50 p-1">
          {templates.map((t) => (
            <button
              key={t.id}
              className="w-full text-left p-2.5 rounded-md hover:bg-muted transition-colors flex items-start gap-2"
              onClick={() => { onSelect(t.id); setOpen(false); }}
            >
              <div className="mt-0.5 text-primary">{t.icon}</div>
              <div>
                <div className="text-sm font-medium">{t.label}</div>
                <div className="text-xs text-muted-foreground">{t.desc}</div>
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------- Demo Template Builder ----------

function makeNode(
  id: string,
  typeStr: string,
  x: number,
  y: number,
  configOverrides?: Record<string, unknown>,
  labelOverride?: string
): Node<WorkflowNodeData> | null {
  const tpl = nodeTemplates.find((t) => t.type === typeStr);
  if (!tpl) return null;
  return {
    id,
    type: tpl.type,
    position: { x, y },
    data: {
      label: labelOverride ?? tpl.label,
      type: tpl.type as WorkflowNodeData['type'],
      description: tpl.description,
      icon: tpl.icon,
      color: tpl.color,
      status: 'idle',
      config: { ...tpl.defaultConfig, ...(configOverrides || {}) },
      inputs: tpl.inputs,
      outputs: tpl.outputs,
    },
  };
}

function buildDemoTemplate(id: string): { name: string; nodes: Node<WorkflowNodeData>[]; edges: Edge[] } | null {
  switch (id) {
    case 'qualia-three-branch': {
      // Chain A: HF → Camera & Noise → Trajectory Noise → Output A
      const a1 = makeNode('q3_hf_dataset', 'hf_dataset', 0, 0, { datasetId: 'lerobot/pusht', datasetType: 'lerobot_v3' }, 'HF Dataset');
      const a2 = makeNode('q3_camera_noise', 'camera_noise', 280, 0, { transforms: 'lighting,noise', copies: 3, mode: 'stacked' }, 'Camera & Noise');
      const a3 = makeNode('q3_traj_noise', 'trajectory_noise', 560, 0, { strength: 0.1, jointNoise: true }, 'Trajectory Noise');
      const a4 = makeNode('q3_output_a', 'output_dataset', 840, 0, { outputName: 'output_dataset_a' }, 'Output Dataset A');

      // Chain B: Ego → World Model → Depth → Pose → Output B
      const b1 = makeNode('q3_ego_1', 'ego_dataset', 0, 220, { source: '', prompt: 'robot manipulation scene' }, 'Ego Dataset');
      const b2 = makeNode('q3_world_model', 'world_model_generator', 280, 220, {}, 'World Model Generator');
      const b3 = makeNode('q3_depth', 'depth_estimator', 560, 220, {}, 'Depth Estimator');
      const b4 = makeNode('q3_pose', 'pose_action_extractor', 840, 220, {}, 'Pose & Action Extractor');
      const b5 = makeNode('q3_output_b', 'output_dataset', 1120, 220, { outputName: 'output_dataset_b' }, 'Output Dataset B');

      // Chain C: Ego → URDF Inpaint → IDM → Output C
      const c1 = makeNode('q3_ego_2', 'ego_dataset', 0, 440, { source: '', prompt: 'robot arm demo' }, 'Ego Dataset');
      const c2 = makeNode('q3_urdf', 'urdf_inpaint', 280, 440, {}, 'URDF Inpaint');
      const c3 = makeNode('q3_idm', 'idm_inverse_dynamics', 560, 440, {}, 'IDM Inverse Dynamics');
      const c4 = makeNode('q3_output_c', 'output_dataset', 840, 440, { outputName: 'output_dataset_c' }, 'Output Dataset C');

      // Merge + foundation models (matches Qualia Studio doc diagram)
      const m1 = makeNode('q3_merge', 'merge_datasets', 1380, 220, {}, 'Merge Output Datasets');
      const t1 = makeNode('q3_pi05', 'qualia_finetune', 1680, 80, { vlaType: 'pi05', hours: 4, instanceType: 'A100', jobName: 'pi05_finetune' }, 'Pi0.5 Finetune');
      const t2 = makeNode('q3_cosmos', 'qualia_finetune', 1680, 360, { vlaType: 'pi0', hours: 2, instanceType: 'A100', jobName: 'cosmos_policy' }, 'Cosmos Policy Finetune');
      const r1 = makeNode('q3_reward', 'reward_model_tuning', 1120, 0, { headMode: 'dense', instanceType: 'H100', hours: 2 }, 'Reward Model Tuning');
      const mon = makeNode('q3_monitor', 'job_monitor', 1980, 220, { pollIntervalSec: 5, timeoutMin: 120 }, 'Job Monitor');

      const nodes = [a1, a2, a3, a4, b1, b2, b3, b4, b5, c1, c2, c3, c4, m1, t1, t2, r1, mon].filter(Boolean) as Node<WorkflowNodeData>[];
      const edges: Edge[] = [
        // Chain A
        { id: 'eq3_a1', source: 'q3_hf_dataset', target: 'q3_camera_noise', sourceHandle: 'dataset', targetHandle: 'dataset' },
        { id: 'eq3_a2', source: 'q3_camera_noise', target: 'q3_traj_noise', sourceHandle: 'dataset_out', targetHandle: 'dataset' },
        { id: 'eq3_a3', source: 'q3_traj_noise', target: 'q3_output_a', sourceHandle: 'dataset_out', targetHandle: 'dataset' },
        // Chain B
        { id: 'eq3_b1', source: 'q3_ego_1', target: 'q3_world_model', sourceHandle: 'ego_video', targetHandle: 'ego_video' },
        { id: 'eq3_b2', source: 'q3_world_model', target: 'q3_depth', sourceHandle: 'dataset_out', targetHandle: 'ego_video' },
        { id: 'eq3_b3', source: 'q3_depth', target: 'q3_pose', sourceHandle: 'dataset_out', targetHandle: 'dataset' },
        { id: 'eq3_b4', source: 'q3_pose', target: 'q3_output_b', sourceHandle: 'dataset_out', targetHandle: 'dataset' },
        // Chain C
        { id: 'eq3_c1', source: 'q3_ego_2', target: 'q3_urdf', sourceHandle: 'ego_video', targetHandle: 'ego_video' },
        { id: 'eq3_c2', source: 'q3_urdf', target: 'q3_idm', sourceHandle: 'dataset_out', targetHandle: 'ego_video' },
        { id: 'eq3_c3', source: 'q3_idm', target: 'q3_output_c', sourceHandle: 'dataset_out', targetHandle: 'dataset' },
        // Merge
        { id: 'eq3_m1', source: 'q3_output_a', target: 'q3_merge', sourceHandle: 'dataset_out', targetHandle: 'dataset_1' },
        { id: 'eq3_m2', source: 'q3_output_b', target: 'q3_merge', sourceHandle: 'dataset_out', targetHandle: 'dataset_2' },
        { id: 'eq3_m3', source: 'q3_output_c', target: 'q3_merge', sourceHandle: 'dataset_out', targetHandle: 'dataset_3' },
        // Training
        { id: 'eq3_t1', source: 'q3_merge', target: 'q3_pi05', sourceHandle: 'merged', targetHandle: 'dataset' },
        { id: 'eq3_t2', source: 'q3_merge', target: 'q3_cosmos', sourceHandle: 'merged', targetHandle: 'dataset' },
        { id: 'eq3_t3', source: 'q3_pi05', target: 'q3_monitor', sourceHandle: 'job', targetHandle: 'job' },
        // Reward from Chain A directly
        { id: 'eq3_r1', source: 'q3_output_a', target: 'q3_reward', sourceHandle: 'dataset_out', targetHandle: 'dataset' },
      ];
      return { name: 'Qualia Studio Three-Branch Demo', nodes, edges };
    }

    case 'skill-factory': {
      const n1 = makeNode('sf_dataset', 'dataset_load', 0, 0, { datasetId: 'lerobot/pusht', imageKeys: ['observation.image'] });
      const n2 = makeNode('sf_camera', 'camera_map', 300, 0, { mappings: [{ slot: 'cam_1', imageKey: 'observation.image' }] });
      const n3 = makeNode('sf_finetune', 'finetune_job', 600, 0, { vlaType: 'act', hours: 2, instanceType: 'A100' });
      const n4 = makeNode('sf_monitor', 'job_monitor', 900, 0, { pollIntervalSec: 5, timeoutMin: 60 });
      const n5 = makeNode('sf_evaluate', 'evaluate', 1200, 0, { passThreshold: 0.7 });
      const n6 = makeNode('sf_publish', 'publish_skill', 1500, 0, { skillName: 'push_t_skill', verb: 'push', version: '1.0.0' });
      const nodes = [n1, n2, n3, n4, n5, n6].filter(Boolean) as Node<WorkflowNodeData>[];
      const edges: Edge[] = [
        { id: 'e_sf_1', source: 'sf_dataset', target: 'sf_camera', sourceHandle: 'dataset', targetHandle: 'dataset' },
        { id: 'e_sf_2', source: 'sf_camera', target: 'sf_finetune', sourceHandle: 'mapping', targetHandle: 'mapping' },
        { id: 'e_sf_2b', source: 'sf_dataset', target: 'sf_finetune', sourceHandle: 'dataset', targetHandle: 'dataset' },
        { id: 'e_sf_3', source: 'sf_finetune', target: 'sf_monitor', sourceHandle: 'job', targetHandle: 'job' },
        { id: 'e_sf_4', source: 'sf_monitor', target: 'sf_evaluate', sourceHandle: 'model', targetHandle: 'model' },
        { id: 'e_sf_5', source: 'sf_evaluate', target: 'sf_publish', sourceHandle: 'metrics', targetHandle: 'metrics' },
      ];
      return { name: 'Skill Factory', nodes, edges };
    }

    case 'so101-recording': {
      const n1 = makeNode('so_start', 'record_dataset_start', 0, 0, {
        leaderPort: '/dev/ttyACM0', followerPort: '/dev/ttyACM1',
        taskName: 'pick_place', episodes: 3, fps: 30, cameraIds: '0',
      });
      const n2 = makeNode('so_monitor', 'recording_monitor', 350, 0, { pollIntervalSec: 3 });
      const n3 = makeNode('so_check', 'dataset_check', 700, 0);
      const nodes = [n1, n2, n3].filter(Boolean) as Node<WorkflowNodeData>[];
      const edges: Edge[] = [
        { id: 'e_so_1', source: 'so_start', target: 'so_monitor', sourceHandle: 'recording', targetHandle: 'recording' },
        { id: 'e_so_2', source: 'so_monitor', target: 'so_check', sourceHandle: 'recording_out', targetHandle: 'recording' },
      ];
      return { name: 'SO-101 Record Dataset', nodes, edges };
    }

    case 'reachy-recording': {
      const n1 = makeNode('rc_daemon', 'reachy_daemon_check', 0, 0);
      const n2 = makeNode('rc_record', 'reachy_record_move', 350, 0, { moveName: 'wave_hello', durationS: 5, sampleHz: 100 });
      const n3 = makeNode('rc_output', 'reachy_move_output', 700, 0);
      const nodes = [n1, n2, n3].filter(Boolean) as Node<WorkflowNodeData>[];
      const edges: Edge[] = [
        { id: 'e_rc_1', source: 'rc_daemon', target: 'rc_record', sourceHandle: 'daemon', targetHandle: 'daemon' },
        { id: 'e_rc_2', source: 'rc_record', target: 'rc_output', sourceHandle: 'trajectory', targetHandle: 'trajectory' },
      ];
      return { name: 'Reachy Record Move', nodes, edges };
    }

    case 'run-skill': {
      const n1 = makeNode('rs_invoke', 'skill_invoke', 0, 0, {
        skillId: '', runtimeId: '', params: {},
      });
      const nodes = [n1].filter(Boolean) as Node<WorkflowNodeData>[];
      return { name: 'Run Installed Skill', nodes, edges: [] };
    }

    default:
      return null;
  }
}

/**
 * 尝试用现有模板补齐节点结构，以兼容旧版本或部分损坏的 JSON。
 * 未知类型返回 null（外层会跳过）。
 */
function reconcileNode(n: Node<WorkflowNodeData>): Node<WorkflowNodeData> | null {
  if (!n?.data?.type) return null;
  const tpl = findNodeTemplate(n.data.type);
  if (!tpl) return null;
  return {
    ...n,
    type: n.type || tpl.type,
    data: {
      ...n.data,
      label: n.data.label || tpl.label,
      description: n.data.description || tpl.description,
      icon: n.data.icon || tpl.icon,
      color: n.data.color || tpl.color,
      status: 'idle',
      progress: undefined,
      validationErrors: undefined,
      config: { ...tpl.defaultConfig, ...(n.data.config || {}) },
      inputs: tpl.inputs,
      outputs: tpl.outputs,
    },
  };
}

export function WorkflowEditor() {
  return (
    <ReactFlowProvider>
      <WorkflowEditorInner />
    </ReactFlowProvider>
  );
}
