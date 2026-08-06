import { requestJson } from './http'

interface CreateAgentPublishResponse {
  published: Record<string, any>
}

export const createAgentApi = {
  publish: (workspaceId: string, confirmation = '用户在 Web 界面点击发布') =>
    requestJson<CreateAgentPublishResponse>(
      `/api/create-agent/workspaces/${encodeURIComponent(workspaceId)}/publish`,
      {
        method: 'POST',
        body: JSON.stringify({ confirmation }),
      },
    ),
  putResource: (workspaceId: string, resourceId: string, value: unknown) =>
    requestJson(`/api/create-agent/workspaces/${encodeURIComponent(workspaceId)}/resources/${encodeURIComponent(resourceId)}`, {
      method: 'PUT',
      body: JSON.stringify({ value }),
    }),
}
