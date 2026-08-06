import type { ToolActivity } from '@/types/protocol'

export type ToolActivityDisplayStatus = ToolActivity['status'] | 'approved' | 'rejected'

export function toolActivityDisplayStatus(tool: ToolActivity): ToolActivityDisplayStatus {
  if (tool.status === 'approval') {
    if (tool.approvalState === 'approved') return 'approved'
    if (tool.approvalState === 'denied' || tool.approvalState === 'rejected') return 'rejected'
  }
  return tool.status
}

export function isToolActivityPendingApproval(tool: ToolActivity): boolean {
  return tool.status === 'approval' && (!tool.approvalState || tool.approvalState === 'pending')
}

export function isToolActivityActive(tool: ToolActivity): boolean {
  return tool.status === 'proposed' || tool.status === 'started' || isToolActivityPendingApproval(tool)
}

