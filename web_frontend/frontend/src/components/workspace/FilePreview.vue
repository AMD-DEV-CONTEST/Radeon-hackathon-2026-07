<template>
  <div class="file-preview-container">
    <div class="preview-header">
      <div class="file-info">
        <ResourceIcon :name="file.name" :mime-type="file.mimeType" :size="28" />
        <span class="file-info-copy">
          <n-text strong class="file-name" :title="file.name">{{ file.name }}</n-text>
          <n-text depth="3" class="file-meta">
            {{ formatFileSize(file.sizeBytes) }} · {{ previewLabel }}
          </n-text>
        </span>
      </div>
      <div class="preview-actions">
        <n-button size="small" @click="addToReferences">
          <template #icon>
            <n-icon><AddCircleOutline /></n-icon>
          </template>
          {{ t('references.add') }}
        </n-button>
        <n-button size="small" @click="handleDownload">
          <template #icon>
            <n-icon><Download /></n-icon>
          </template>
          {{ desktopFileActionsAvailable ? t('workspace.saveAs') : t('common.download') }}
        </n-button>
        <n-button v-if="desktopFileActionsAvailable" size="small" @click="handleReveal">
          <template #icon>
            <n-icon><FolderOpenOutline /></n-icon>
          </template>
          {{ t('workspace.revealInFileManager') }}
        </n-button>
        <n-popconfirm @positive-click="handleDelete">
          <template #trigger>
            <n-button size="small" type="error" secondary>
              <template #icon><n-icon><TrashOutline /></n-icon></template>
              {{ t('workspace.deleteFile') }}
            </n-button>
          </template>
          {{ t('workspace.deleteFileConfirm', { name: file.name }) }}
        </n-popconfirm>
        <n-button size="small" @click="handleClose">
          <template #icon>
            <n-icon><Close /></n-icon>
          </template>
          {{ t('common.close') }}
        </n-button>
      </div>
    </div>

    <FilePreviewContent :file="file" :source-url="rawFileUrl" />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NButton, NIcon, NPopconfirm, NText } from 'naive-ui'
import { AddCircleOutline, Close, Download, FolderOpenOutline, TrashOutline } from '@/components/icons'
import { workspaceApi } from '@/api/workspace'
import {
  desktopWorkspaceFileActionsAvailable,
  revealWorkspaceEntry,
  saveWorkspaceFileAs,
} from '@/api/desktopWorkspaceFiles'
import { useI18n } from '@/composables/useI18n'
import type { WorkspaceRequestContext, WorkspaceScope } from '@/api/resourceTypes'
import type { WorkspaceFileView } from '@/types/protocol'
import { useContextReferenceStore } from '@/stores/contextReferences'
import { workspaceFileContextReference } from '@/utils/contextReferences'
import { useMessage } from 'naive-ui'
import FilePreviewContent from './FilePreviewContent.vue'
import ResourceIcon from '@/components/common/ResourceIcon.vue'
import { fileExtension, filePreviewKind } from '@/utils/filePreview'

const props = defineProps<{
  file: WorkspaceFileView
}>()

const emit = defineEmits<{
  close: []
  deleted: [path: string]
}>()

const { t } = useI18n()
const message = useMessage()
const referenceStore = useContextReferenceStore()
const desktopFileActionsAvailable = desktopWorkspaceFileActionsAvailable()
const extension = computed(() => fileExtension(props.file))
const previewKind = computed(() => filePreviewKind(props.file))
const previewLabel = computed(() => {
  if (previewKind.value === 'markdown') return 'Markdown'
  if (previewKind.value === 'code') return extension.value.toUpperCase()
  if (previewKind.value === 'image') return t('workspace.preview.image')
  if (previewKind.value === 'pdf') return 'PDF'
  if (previewKind.value === 'text' && props.file.payload?.preview_mode === 'extracted_text') return t('workspace.preview.documentText')
  if (previewKind.value === 'text') return t('workspace.preview.text')
  return t('workspace.preview.binary')
})
const packageId = computed(() => {
  const payload = props.file.payload || {}
  return String(payload.package_id || payload.packageId || '').trim() || null
})
const workspaceContext = computed<WorkspaceRequestContext>(() => {
  const payload = props.file.payload || {}
  return {
    resourceMode: payload.resource_mode || payload.resourceMode || 'package',
    packageId: packageId.value,
    packageSessionId: String(payload.package_session_id || payload.packageSessionId || '').trim() || null,
    workspaceId: String(payload.workspace_id || payload.workspaceId || '').trim() || null,
    factorySessionId: String(payload.factory_session_id || payload.factorySessionId || '').trim() || null,
    createAgentSessionId: String(payload.create_agent_session_id || payload.createAgentSessionId || '').trim() || null,
    groupId: String(payload.group_id || payload.groupId || '').trim() || null,
  }
})
const rawFileUrl = computed(() => {
  if (!props.file.path) return ''
  const scope = (props.file.scope || 'workdir') as WorkspaceScope
  return workspaceApi.rawUrl(scope, props.file.path, workspaceContext.value)
})

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

async function handleDownload() {
  if (desktopFileActionsAvailable && props.file.path) {
    try {
      const scope = (props.file.scope || 'workdir') as WorkspaceScope
      const destination = await saveWorkspaceFileAs(
        scope,
        props.file.path,
        workspaceContext.value,
      )
      if (destination) {
        message.success(t('workspace.fileSavedAs', { path: destination }))
      }
    } catch (error) {
      message.error(error instanceof Error ? error.message : String(error))
    }
    return
  }

  if (rawFileUrl.value) {
    const anchor = document.createElement('a')
    anchor.href = rawFileUrl.value
    anchor.download = props.file.name
    anchor.click()
    return
  }

  const blob = props.file.contentBase64
    ? base64Blob(props.file.contentBase64, props.file.mimeType || 'application/octet-stream')
    : new Blob([props.file.content], { type: props.file.mimeType || 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = props.file.name
  anchor.click()
  URL.revokeObjectURL(url)
}

async function handleReveal() {
  if (!props.file.path) return
  try {
    const scope = (props.file.scope || 'workdir') as WorkspaceScope
    await revealWorkspaceEntry(scope, props.file.path, workspaceContext.value)
  } catch (error) {
    message.error(error instanceof Error ? error.message : String(error))
  }
}

async function handleDelete() {
  if (!props.file.path) return
  const scope = (props.file.scope || 'workdir') as WorkspaceScope
  await workspaceApi.deleteFile(scope, props.file.path, workspaceContext.value)
  message.success(t('workspace.fileDeleted'))
  emit('deleted', props.file.path)
}

function addToReferences() {
  const reference = workspaceFileContextReference(props.file)
  if (!reference) {
    message.warning(t('references.unsupportedFile'))
    return
  }
  if (!referenceStore.add(reference)) {
    message.warning(t('references.limitReached'))
    return
  }
  message.success(t('references.added'))
}

function base64Blob(content: string, mimeType: string): Blob {
  const binary = atob(content)
  const bytes = new Uint8Array(binary.length)
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index)
  }
  return new Blob([bytes], { type: mimeType })
}

function handleClose() {
  emit('close')
}

</script>

<style scoped>
.file-preview-container {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--app-surface);
  container-type: inline-size;
}

.preview-header {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: start;
  gap: var(--app-space-md);
  padding: var(--app-space-md) var(--app-space-lg);
  border-bottom: 1px solid var(--app-divider);
  background: var(--app-surface-muted);
}

.file-info {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: var(--app-space-sm);
}

.file-info-copy {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 4px;
}

.file-name {
  min-width: 0;
  overflow: hidden;
  display: -webkit-box;
  overflow-wrap: anywhere;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.file-meta {
  font-size: 12px;
}

.preview-actions {
  min-width: 0;
  max-width: 360px;
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: var(--app-space-sm);
}

.preview-actions :deep(.n-button) {
  flex: 0 0 auto;
}

@container (max-width: 640px) {
  .preview-header {
    grid-template-columns: minmax(0, 1fr);
    gap: var(--app-space-sm);
    padding-inline: var(--app-space-md);
  }

  .preview-actions {
    width: 100%;
    max-width: none;
    justify-content: flex-start;
  }
}

</style>
