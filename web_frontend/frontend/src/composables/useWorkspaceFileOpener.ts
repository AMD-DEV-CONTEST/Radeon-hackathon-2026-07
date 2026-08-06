import type { WorkspaceRequestContext, WorkspaceScope } from '@/api/resourceTypes'
import { useCommand } from '@/composables/useCommand'
import { useRuntimeStore } from '@/stores/runtime'
import { useUiStore } from '@/stores/ui'
import { useWorkspaceStore } from '@/stores/workspace'
import { workspaceFileReference } from '@/utils/workspaceResources'

const WORKSPACE_PREVIEW_MAX_CHARS = 1_000_000

export function useWorkspaceFileOpener() {
  const commands = useCommand()
  const runtimeStore = useRuntimeStore()
  const uiStore = useUiStore()
  const workspaceStore = useWorkspaceStore()

  async function openWorkspaceFile(
    source: string,
    context: WorkspaceRequestContext | null | undefined,
    defaultScope: WorkspaceScope = 'workdir',
  ): Promise<boolean> {
    const reference = workspaceFileReference(source, defaultScope)
    if (!reference || !context) return false

    uiStore.setConversationDockPanel('workspace')
    workspaceStore.setScope(reference.scope)
    runtimeStore.workspaceFile = null
    await commands.readFile(
      reference.scope,
      reference.path,
      context,
      WORKSPACE_PREVIEW_MAX_CHARS,
    )
    return runtimeStore.workspaceFile !== null
  }

  return {
    openWorkspaceFile,
  }
}
