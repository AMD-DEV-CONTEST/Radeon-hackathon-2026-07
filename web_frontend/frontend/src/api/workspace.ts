import type { WorkspaceContextInput, WorkspaceRequestContext, WorkspaceScope } from './resourceTypes'
import type { WorkspaceMountView } from '@/types/protocol'
import { resolvedBackendUrl } from './backendUrl'
import { requestEvent, requestJson, withQuery } from './http'

export const workspaceApi = {
  projects: () =>
    requestJson<{ workspaces: WorkspaceProjectView[] }>('/api/workspace/projects'),
  directoryRoots: () =>
    requestJson<{ roots: WorkspaceDirectoryView[] }>('/api/workspace/directory-roots'),
  directories: (path: string) =>
    requestJson<WorkspaceDirectoryListing>(
      withQuery('/api/workspace/directories', { path }),
    ),
  createProject: (payload: {
    title?: string | null
    mode?: WorkspaceProjectMode
    root_kind?: WorkspaceRootKind
    workdir_root?: string | null
    owner_package_id?: string | null
  }) =>
    requestJson<{ workspace: WorkspaceProjectView }>('/api/workspace/projects', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  updateProject: (
    workspaceId: string,
    payload: { title?: string; mode?: WorkspaceProjectMode; archived?: boolean },
  ) =>
    requestJson<{ workspace: WorkspaceProjectView }>(
      `/api/workspace/projects/${encodeURIComponent(workspaceId)}`,
      { method: 'PATCH', body: JSON.stringify(payload) },
    ),
  roots: (context?: WorkspaceContextInput) =>
    requestEvent(withQuery('/api/workspace/roots', workspaceQuery(context))),
  entries: (scope: WorkspaceScope, path: string, context?: WorkspaceContextInput) =>
    requestEvent(withQuery('/api/workspace/entries', { scope, path, ...workspaceQuery(context) })),
  file: (scope: WorkspaceScope, path: string, context?: WorkspaceContextInput, maxChars?: number) =>
    requestEvent(withQuery('/api/workspace/file', { scope, path, ...workspaceQuery(context), max_chars: maxChars })),
  rawUrl: (scope: WorkspaceScope, path: string, context?: WorkspaceContextInput) =>
    resolvedBackendUrl(withQuery('/api/workspace/raw', { scope, path, ...workspaceQuery(context) })),
  nativePath: (scope: WorkspaceScope, path: string, context?: WorkspaceContextInput) =>
    requestJson<{ native_path: string; kind: 'file' | 'directory' }>(
      withQuery('/api/workspace/native-path', { scope, path, ...workspaceQuery(context) }),
    ),
  deleteFile: (scope: WorkspaceScope, path: string, context?: WorkspaceContextInput) =>
    requestJson<{ deleted: boolean; path: string }>(
      withQuery('/api/workspace/file', { scope, path, ...workspaceQuery(context) }),
      { method: 'DELETE' },
    ),
  mounts: async (context?: WorkspaceContextInput) => {
    const response = await requestJson<{ mounts: RawWorkspaceMount[] }>(
      withQuery('/api/workspace/mounts', workspaceQuery(context)),
    )
    return { mounts: response.mounts.map(workspaceMountView) }
  },
  mountDirectory: async (sourcePath: string, context?: WorkspaceContextInput, name?: string) => {
    const response = await requestJson<{ mount: RawWorkspaceMount; created: boolean }>(
      withQuery('/api/workspace/mounts', workspaceQuery(context)),
      {
        method: 'POST',
        body: JSON.stringify({
          source_path: sourcePath,
          name: name?.trim() || null,
        }),
      },
    )
    return {
      mount: workspaceMountView(response.mount),
      created: response.created,
    }
  },
  unmountDirectory: (mountId: string, context?: WorkspaceContextInput) =>
    requestJson<{ mount_id: string; removed: boolean }>(
      withQuery(`/api/workspace/mounts/${encodeURIComponent(mountId)}`, workspaceQuery(context)),
      { method: 'DELETE' },
    ),
}

export type WorkspaceProjectMode = 'isolated' | 'project'
export type WorkspaceRootKind = 'managed' | 'linked'

export interface WorkspaceProjectView {
  workspace_id: string
  title: string
  mode: WorkspaceProjectMode
  root_kind: WorkspaceRootKind
  owner_package_id: string | null
  workdir_root: string
  archived: boolean
  created_at: string
  updated_at: string
}

export interface WorkspaceDirectoryView {
  name: string
  path: string
}

export interface WorkspaceDirectoryListing {
  path: string
  parent: string | null
  directories: WorkspaceDirectoryView[]
}

interface RawWorkspaceMount {
  mount_id?: string
  name?: string
  source_path?: string
  created_at?: string
  connected?: boolean
}

function workspaceMountView(value: RawWorkspaceMount): WorkspaceMountView {
  return {
    mountId: String(value.mount_id || ''),
    name: String(value.name || ''),
    sourcePath: String(value.source_path || ''),
    createdAt: String(value.created_at || ''),
    connected: value.connected === true,
  }
}

function workspaceQuery(context: WorkspaceContextInput): Record<string, string | undefined | null> {
  if (typeof context === 'string') {
    return { package_id: context }
  }
  const normalized = normalizeWorkspaceContext(context)
  return {
    resource_mode: normalized.resourceMode,
    package_id: normalized.packageId,
    package_session_id: normalized.packageSessionId,
    workspace_id: normalized.workspaceId,
    factory_session_id: normalized.factorySessionId,
    create_agent_session_id: normalized.createAgentSessionId,
    group_id: normalized.groupId,
  }
}

function normalizeWorkspaceContext(context: WorkspaceContextInput): WorkspaceRequestContext {
  return context && typeof context === 'object' ? context : {}
}
