import { requestJson } from './http'

export interface ConversationStorageUsage {
  bytes_used: number
  file_count: number
  factory_session_count: number
  agent_session_count: number
  background_task_session_count: number
  session_count: number
}

export interface ConversationStorageClearResult {
  cleared: boolean
  before: ConversationStorageUsage
  after: ConversationStorageUsage
  released_bytes: number
}

export const storageApi = {
  conversationUsage: () =>
    requestJson<ConversationStorageUsage>('/api/storage/conversations'),
  clearConversations: () =>
    requestJson<ConversationStorageClearResult>('/api/storage/conversations/clear', {
      method: 'POST',
      body: JSON.stringify({ confirmed: true }),
    }),
}
