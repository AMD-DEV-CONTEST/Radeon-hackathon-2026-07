import type { Node } from '@xyflow/react'
import type { LayoutConfig } from './LayoutToolbar'

function sortableValue(node: Node, key: 'status' | 'name' | 'agent_type'): string {
  const data = node.data as Record<string, unknown>
  if (key === 'status') return String(data.status ?? '')
  if (key === 'agent_type') return String(data.agentType ?? '')
  return String(data.name ?? node.id)
}

export function applyLayout(nodes: Node[], config: LayoutConfig): Node[] {
  const gap = 20
  const nodeWidth = 280
  const nodeHeight = 180

  const sorted = [...nodes].sort((a, b) =>
    sortableValue(a, config.sortBy).localeCompare(sortableValue(b, config.sortBy)),
  )

  const groups: Record<string, Node[]> = {}
  if (config.groupBy === 'none') {
    groups[''] = sorted
  } else {
    for (const node of sorted) {
      const key = config.groupBy === 'status'
        ? sortableValue(node, 'status') || 'unknown'
        : sortableValue(node, 'agent_type') || 'unknown'
      groups[key] ??= []
      groups[key].push(node)
    }
  }

  const positioned: Node[] = []
  let globalY = 0

  if (config.mode === 'grid') {
    const cols = 3
    let row = 0
    let col = 0
    for (const node of sorted) {
      positioned.push({
        ...node,
        position: { x: col * (nodeWidth + gap), y: row * (nodeHeight + gap) },
      })
      col += 1
      if (col >= cols) {
        col = 0
        row += 1
      }
    }
  } else if (config.mode === 'list') {
    for (const key of Object.keys(groups)) {
      const groupNodes = groups[key]
      let groupX = 0
      for (const node of groupNodes) {
        positioned.push({
          ...node,
          position: { x: groupX, y: globalY },
        })
        groupX += nodeWidth + gap
        if (groupX > 800) {
          groupX = 0
          globalY += nodeHeight + gap
        }
      }
      globalY += nodeHeight + gap + 10
    }
  } else {
    const cols = 4
    let row = 0
    let col = 0
    for (const node of sorted) {
      positioned.push({
        ...node,
        position: { x: col * (220 + gap), y: row * (120 + gap) },
      })
      col += 1
      if (col >= cols) {
        col = 0
        row += 1
      }
    }
  }

  return positioned
}
