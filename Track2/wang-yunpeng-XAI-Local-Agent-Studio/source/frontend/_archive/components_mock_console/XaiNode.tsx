import { Handle, Position, type NodeProps } from 'reactflow'
import { NODE_META, STATUS_LABEL } from '../blueprint'
import type { SimNodeData } from '../sim/simulator'

export function XaiNode({ data, selected }: NodeProps<SimNodeData>) {
  const meta = NODE_META[data.kind]
  return (
    <div className={`xnode xnode-${data.status} ${selected ? 'xnode-sel' : ''}`} style={{ borderColor: meta.color }}>
      <Handle type="target" position={Position.Left} />
      <div className="xnode-head" style={{ background: meta.color }}>
        <span className="xnode-icon">{meta.icon}</span>
        <span>{meta.label}</span>
        <span className="xnode-mod">{meta.module}</span>
      </div>
      <div className="xnode-body">
        <div className="xnode-name">{data.label}</div>
        <div className={`xnode-status st-${data.status}`}>{STATUS_LABEL[data.status]}</div>
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  )
}
