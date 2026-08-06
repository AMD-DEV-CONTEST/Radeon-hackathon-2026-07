import { useCallback, useEffect, useRef, useState } from 'react'
import ReactFlow, {
  Background, Controls, MiniMap, addEdge, useNodesState, useEdgesState,
  type Connection, type Edge, type Node, type NodeMouseHandler,
} from 'reactflow'
import { XaiNode } from './XaiNode'
import { NODE_META, NODE_ORDER, type NodeKind, type NodeStatus } from '../blueprint'
import { topoSort, runSimulation } from '../sim/simulator'
import { useStore } from '../store'

const nodeTypes = { xai: XaiNode }

const seedNodes: Node[] = [
  { id: 'n0', type: 'xai', position: { x: 40, y: 200 }, data: { kind: 'intent_router', label: '意图路由（自动分发）', status: 'idle' } },
  { id: 'n1', type: 'xai', position: { x: 320, y: 40 }, data: { kind: 'openclaw', label: '执行网关 OpenClaw', status: 'idle' } },
  { id: 'n2', type: 'xai', position: { x: 320, y: 140 }, data: { kind: 'grok_build', label: '代码引擎 Grok Build', status: 'idle' } },
  { id: 'n3', type: 'xai', position: { x: 320, y: 240 }, data: { kind: 'scheduler', label: '调度中台 Orchestrator', status: 'idle' } },
  { id: 'n4', type: 'xai', position: { x: 320, y: 340 }, data: { kind: 'hermes', label: '记忆大脑 Hermes', status: 'idle' } },
  { id: 'n5', type: 'xai', position: { x: 640, y: 200 }, data: { kind: 'kb', label: '全局统一记忆池', status: 'idle' } },
  { id: 'n6', type: 'xai', position: { x: 920, y: 200 }, data: { kind: 'human', label: '权限分级(P0二次确认)', status: 'idle' } },
  { id: 'n7', type: 'xai', position: { x: 1200, y: 200 }, data: { kind: 'reflect', label: '元认知校准 Meta', status: 'idle' } },
]

const seedEdges: Edge[] = [
  { id: 'e0-1', source: 'n0', target: 'n1', animated: true },
  { id: 'e0-2', source: 'n0', target: 'n2', animated: true },
  { id: 'e0-3', source: 'n0', target: 'n3', animated: true },
  { id: 'e0-4', source: 'n0', target: 'n4', animated: true },
  { id: 'e1-5', source: 'n1', target: 'n5', animated: true },
  { id: 'e2-5', source: 'n2', target: 'n5', animated: true },
  { id: 'e3-5', source: 'n3', target: 'n5', animated: true },
  { id: 'e4-5', source: 'n4', target: 'n5', animated: true },
  { id: 'e5-6', source: 'n5', target: 'n6', animated: true },
  { id: 'e6-7', source: 'n6', target: 'n7', animated: true },
]

export function Canvas() {
  const [nodes, setNodes, onNodesChange] = useNodesState(seedNodes)
  const [edges, setEdges, onEdgesChange] = useEdgesState(seedEdges)
  const nodesRef = useRef(nodes)
  const counter = useRef(100)
  const [running, setRunning] = useState(false)

  useEffect(() => { nodesRef.current = nodes }, [nodes])

  const setStatus = useCallback((id: string, status: NodeStatus) => {
    setNodes((nds) => nds.map((n) => {
      if (n.id !== id) return n
      const next = { ...n, data: { ...n.data, status } }
      if (useStore.getState().selectedNode === id) {
        useStore.getState().setSelectedNodeMeta({ kind: next.data.kind, label: next.data.label, status })
      }
      return next
    }))
  }, [setNodes])

  const onConnect = useCallback((c: Connection) => setEdges((eds) => addEdge({ ...c, animated: true }, eds)), [setEdges])

  const onNodeClick: NodeMouseHandler = useCallback((_, node) => {
    const d = node.data as { kind: NodeKind; label: string; status: NodeStatus }
    useStore.getState().setSelected(node.id)
    useStore.getState().setSelectedNodeMeta({ kind: d.kind, label: d.label, status: d.status })
  }, [])

  const addNode = useCallback((kind: NodeKind) => {
    const id = `n${++counter.current}`
    const meta = NODE_META[kind]
    setNodes((nds) => [
      ...nds,
      { id, type: 'xai', position: { x: 360 + Math.random() * 200, y: 180 + Math.random() * 160 },
        data: { kind, label: meta.label, status: 'idle' } },
    ])
  }, [setNodes])

  const run = useCallback(async () => {
    const st = useStore.getState()
    if (st.runStatus === 'running') return
    st.setRunStatus('running')
    setRunning(true)
    st.pushEvent('system', '🚀 工作流启动（拓扑执行）')
    setNodes((nds) => nds.map((n) => ({ ...n, data: { ...n.data, status: 'idle' } })))
    st.updateRunner(0, false)
    const order = topoSort(nodesRef.current, edges)
    await runSimulation({
      order,
      getNode: (id) => nodesRef.current.find((n) => n.id === id),
      setStatus,
      onEvent: (type, msg) => useStore.getState().pushEvent(type, msg),
      onGuard: (g) => useStore.getState().addGuard(g),
      onResolveGuard: (id) => useStore.getState().resolveGuard(id),
      onKb: (n) => useStore.getState().setKbHits(n),
      onObs: (tk) => useStore.getState().bumpObs(tk),
      onRunner: (cur, done) => useStore.getState().updateRunner(cur, done),
      delay: 650,
    })
    useStore.getState().setRunStatus('done')
    setRunning(false)
  }, [edges, setNodes, setStatus])

  const reset = useCallback(() => {
    setNodes((nds) => nds.map((n) => ({ ...n, data: { ...n.data, status: 'idle' } })))
    useStore.getState().setRunStatus('idle')
    useStore.getState().updateRunner(0, false)
  }, [setNodes])

  return (
    <div className="canvas-wrap">
      <div className="toolbar">
        <button className="btn-run" onClick={run} disabled={running}>{running ? '执行中…' : '▶ 运行工作流'}</button>
        <button className="btn" onClick={reset}>↺ 重置</button>
        <span className="toolbar-tip">拖拽左侧节点类型到画布 · 连线即数据流 · 双击节点查看右侧检查器</span>
      </div>
      <div className="canvas-body">
        <div className="palette">
          <div className="palette-h">节点面板</div>
          {NODE_ORDER.map((k) => {
            const m = NODE_META[k]
            return (
              <button key={k} className="palette-item" style={{ borderColor: m.color }} onClick={() => addNode(k)}>
                <span>{m.icon}</span> {m.label}
              </button>
            )
          })}
        </div>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onNodeClick={onNodeClick}
          nodeTypes={nodeTypes}
          fitView
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={16} />
          <Controls />
          <MiniMap pannable zoomable />
        </ReactFlow>
      </div>
    </div>
  )
}
