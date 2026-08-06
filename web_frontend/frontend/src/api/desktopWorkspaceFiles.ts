import { invoke, isTauri } from '@tauri-apps/api/core'
import { workspaceApi } from './workspace'
import type { WorkspaceContextInput, WorkspaceScope } from './resourceTypes'

export function desktopWorkspaceFileActionsAvailable(): boolean {
  return isTauri()
}

export async function revealWorkspaceEntry(
  scope: WorkspaceScope,
  path: string,
  context?: WorkspaceContextInput,
): Promise<void> {
  requireDesktopRuntime()
  const resolved = await workspaceApi.nativePath(scope, path, context)
  await invoke('reveal_in_file_manager', { sourcePath: resolved.native_path })
}

export async function saveWorkspaceFileAs(
  scope: WorkspaceScope,
  path: string,
  context?: WorkspaceContextInput,
): Promise<string | null> {
  requireDesktopRuntime()
  const resolved = await workspaceApi.nativePath(scope, path, context)
  if (resolved.kind !== 'file') {
    throw new Error('Only workspace files can be saved as a copy')
  }
  return invoke<string | null>('save_file_as', { sourcePath: resolved.native_path })
}

function requireDesktopRuntime(): void {
  if (!desktopWorkspaceFileActionsAvailable()) {
    throw new Error('This action is available only in the desktop application')
  }
}
