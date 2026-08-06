import { requestJson, withQuery } from './http'

export interface MemoryContextItemView {
  memory_id: string
  source_scope: 'workspace' | 'agent' | 'user' | 'none'
  memory_type: string
  kind: string
  content: string
  score: number
  metadata: Record<string, any>
  namespace: string[]
  updated_at: string | null
}

export interface MemoryQueryResponse {
  package_id: string | null
  namespace: string[]
  namespaces: string[][]
  query: string
  items: MemoryContextItemView[]
  token_estimate: number
  report: Record<string, any>
}

export interface MemoryDeleteResponse {
  deleted: boolean
  memory_id: string
  package_id: string | null
  namespace: string[]
}

export const memoryApi = {
  query: (query: string, packageId?: string, limit = 8, workspaceId?: string | null) =>
    requestJson<MemoryQueryResponse>(withQuery('/api/memory/query', {
      query,
      package_id: packageId,
      workspace_id: workspaceId,
      scope: 'combined',
      limit,
    })),
  deleteItem: (
    memoryId: string,
    scope: 'workspace' | 'agent' | 'user',
    packageId?: string,
    workspaceId?: string | null,
  ) =>
    requestJson<MemoryDeleteResponse>('/api/memory/items', {
      method: 'DELETE',
      body: JSON.stringify({
        memory_id: memoryId,
        package_id: packageId,
        workspace_id: workspaceId,
        scope,
      }),
    }),
}
