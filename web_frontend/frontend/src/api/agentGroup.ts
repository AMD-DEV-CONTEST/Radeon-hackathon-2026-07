/**
 * Agent 群聊系统 - API 客户端
 *
 * 提供类型安全的 HTTP 接口调用
 */

import { requestJson } from './http'
import type { ContextReferenceInput } from '@/types/protocol'

// ===== 类型定义 =====

export type GroupStatus = 'draft' | 'active' | 'archived'
export type MemberRunStatus = 'queued' | 'running' | 'awaiting_approval' | 'completed' | 'failed' | 'cancelled'
export type MessageSpeakerType = 'user' | 'agent' | 'system'
export type MessageKind = 'user_message' | 'agent_response' | 'tool_call' | 'tool_result' | 'approval_request' | 'system_notice' | 'progress'

export interface AgentGroupMemberView {
  group_id: string
  package_id: string
  package_session_id: string
  joined_at: string
  agent_name?: string
  agent_description?: string
}

export interface AgentGroupMessageView {
  message_id: string
  group_id: string
  speaker_type: MessageSpeakerType
  speaker_package_id?: string
  message_kind: MessageKind
  content: string
  reply_to_message_id?: string
  group_run_id?: string
  event_ref?: string
  created_at: string
  context_references?: ContextReferenceInput[]
}

export interface AgentGroupMemberRunView {
  group_run_id: string
  group_id: string
  message_id: string
  speaker_package_id: string
  package_session_id: string
  status: MemberRunStatus
  base_context_version: number
  base_workspace_revision: number
  response_message_id?: string
  request_id?: string
  created_at: string
  updated_at: string
}

export interface AgentGroupSessionView {
  group_id: string
  workspace_id: string
  title: string
  status: GroupStatus
  created_at: string
  updated_at: string
  archived_at?: string
  members: AgentGroupMemberView[]
  messages: AgentGroupMessageView[]
  runs: AgentGroupMemberRunView[]
  current_context_version: number
  current_workspace_revision: number
  workspace_resource?: {
    resource_mode: string
    group_id: string
    workspace_id: string
    workdir: string
  }
}

export interface AgentView {
  package_id: string
  agent_name: string
  agent_description?: string
  status?: string
}

// ===== API 客户端 =====

export const agentGroupApi = {
  // 群聊管理
  async groups(): Promise<{ groups: AgentGroupSessionView[] }> {
    return requestJson('/api/agent-group/groups')
  },

  async createGroup(payload: {
    title: string
    member_package_ids: string[]
    workspace_id?: string
  }): Promise<{ group: AgentGroupSessionView }> {
    return requestJson('/api/agent-group/groups', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },

  async group(groupId: string): Promise<{ group: AgentGroupSessionView }> {
    return requestJson(`/api/agent-group/groups/${groupId}`)
  },

  async updateGroup(
    groupId: string,
    payload: { title?: string; status?: GroupStatus }
  ): Promise<{ group: AgentGroupSessionView }> {
    return requestJson(`/api/agent-group/groups/${groupId}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    })
  },

  async deleteGroup(groupId: string): Promise<{ success: boolean; group_id: string }> {
    return requestJson(`/api/agent-group/groups/${groupId}`, {
      method: 'DELETE',
    })
  },

  // 成员管理
  async addMember(
    groupId: string,
    payload: { package_id: string }
  ): Promise<{ group: AgentGroupSessionView }> {
    return requestJson(`/api/agent-group/groups/${groupId}/members`, {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },

  async removeMember(groupId: string, packageId: string): Promise<{ group: AgentGroupSessionView }> {
    return requestJson(`/api/agent-group/groups/${groupId}/members/${packageId}`, {
      method: 'DELETE',
    })
  },

  // 消息管理
  async sendMessage(
    groupId: string,
    payload: {
      content: string
      client_message_id: string
      target_package_ids: string[]
      reply_to_message_id?: string
      context_references?: ContextReferenceInput[]
    }
  ): Promise<{ group: AgentGroupSessionView }> {
    return requestJson(`/api/agent-group/groups/${groupId}/messages`, {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },

  // Run 管理
  async cancelRun(groupId: string, runId: string): Promise<{ group: AgentGroupSessionView }> {
    return requestJson(`/api/agent-group/groups/${groupId}/runs/${runId}/cancel`, {
      method: 'POST',
    })
  },

  async resumeRun(
    groupId: string,
    runId: string,
    payload: Record<string, unknown>,
  ): Promise<{ group: AgentGroupSessionView }> {
    return requestJson(`/api/agent-group/groups/${groupId}/runs/${runId}/resume`, {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },

  async retryRun(groupId: string, runId: string): Promise<{ group: AgentGroupSessionView }> {
    return requestJson(`/api/agent-group/groups/${groupId}/runs/${runId}/retry`, { method: 'POST' })
  },

  // Agent 列表
  async agents(): Promise<{ agents: AgentView[] }> {
    return requestJson('/api/agent-group/agents')
  },
}
