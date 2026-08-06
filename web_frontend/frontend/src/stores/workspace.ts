/**
 * Workspace Store
 * 管理工作区文件浏览和预览
 */

import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { WorkspaceScope, WorkspaceEntry, WorkspaceFileView, WorkspaceRootView } from '@/types/protocol'

export const useWorkspaceStore = defineStore('workspace', () => {
  const currentScope = ref<WorkspaceScope>('workdir')
  const roots = ref<WorkspaceRootView[]>([])
  const entries = ref<WorkspaceEntry[]>([])
  const currentFile = ref<WorkspaceFileView | null>(null)

  function setScope(scope: WorkspaceScope): void {
    currentScope.value = scope
    entries.value = []
  }

  function setRoots(newRoots: WorkspaceRootView[]): void {
    roots.value = newRoots
  }

  function setEntries(newEntries: WorkspaceEntry[]): void {
    entries.value = newEntries
  }

  function setCurrentFile(file: WorkspaceFileView | null): void {
    currentFile.value = file
  }

  return {
    currentScope,
    roots,
    entries,
    currentFile,
    setScope,
    setRoots,
    setEntries,
    setCurrentFile,
  }
})
