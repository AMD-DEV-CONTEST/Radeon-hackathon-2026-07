<template>
  <div class="workspace-sidebar-content">
    <div v-show="!previewLoading && !runtimeStore.workspaceFile" class="workspace-browser">
      <WorkspaceExplorer
        v-if="workspaceAvailable"
        class="workspace-sidebar-explorer"
        :workspace-context="workspaceRequestContext"
        @select-file="handleWorkspaceFileSelect"
      />
      <div v-else class="workspace-unavailable">
        <n-empty :description="t('workspace.noActiveSession')" size="small" />
      </div>
    </div>
    <div v-if="previewLoading && !runtimeStore.workspaceFile" class="workspace-loading">
      <n-spin size="small" />
      <n-text depth="3">{{ t('workspace.readingFile') }}</n-text>
    </div>
    <FilePreview
      v-if="runtimeStore.workspaceFile"
      :file="runtimeStore.workspaceFile"
      @close="closeWorkspacePreview"
      @deleted="closeWorkspacePreview"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { NEmpty, NSpin, NText } from 'naive-ui'
import { useCommand } from '@/composables/useCommand'
import { useResourceContext } from '@/composables/useResourceContext'
import { useRuntimeStore } from '@/stores/runtime'
import { useUiStore } from '@/stores/ui'
import { useWorkspaceStore } from '@/stores/workspace'
import type { WorkspaceEntry } from '@/types/protocol'
import FilePreview from '@/components/workspace/FilePreview.vue'
import WorkspaceExplorer from '@/components/workspace/WorkspaceExplorer.vue'
import { useI18n } from '@/composables/useI18n'

const uiStore = useUiStore()
const runtimeStore = useRuntimeStore()
const workspaceStore = useWorkspaceStore()
const commands = useCommand()
const resourceContext = useResourceContext()
const { t } = useI18n()
const previewLoading = ref(false)
const WORKSPACE_PREVIEW_MAX_CHARS = 1_000_000

const workspaceRequestContext = computed(() => resourceContext.workspaceContext.value)
const workspaceAvailable = computed(() => resourceContext.workspaceAvailable.value)

async function handleWorkspaceFileSelect(entry: WorkspaceEntry) {
  uiStore.setConversationDockPanel('workspace')
  previewLoading.value = true
  runtimeStore.workspaceFile = null
  await commands.readFile(workspaceStore.currentScope, entry.path, workspaceRequestContext.value, WORKSPACE_PREVIEW_MAX_CHARS)
  if (!runtimeStore.workspaceFile) {
    previewLoading.value = false
  }
}

function closeWorkspacePreview() {
  previewLoading.value = false
  runtimeStore.workspaceFile = null
}

watch(
  () => runtimeStore.workspaceFile,
  (file) => {
    if (file) previewLoading.value = false
  }
)

watch(
  () => resourceContext.workspaceContextKey.value,
  () => {
    workspaceStore.setScope(resourceContext.workspaceDefaultScope.value)
    closeWorkspacePreview()
  },
  { immediate: true }
)
</script>

<style scoped>
.workspace-sidebar-content {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.workspace-browser {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.workspace-sidebar-explorer {
  flex: 1;
  min-height: 0;
}

.workspace-unavailable {
  flex: 1;
  min-height: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--app-space-xl);
}

.workspace-loading {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--app-space-sm);
  color: var(--app-text-muted);
}
</style>
