<template>
  <n-dropdown
    trigger="manual"
    placement="bottom-start"
    :show="contextMenuVisible"
    :x="contextMenuX"
    :y="contextMenuY"
    :options="contextMenuOptions"
    @select="handleContextMenuSelect"
    @clickoutside="closeContextMenu"
  />
  <div class="workspace-explorer">
    <div class="explorer-header">
      <div class="header-title">
        <n-text strong>{{ t('workspace.explorer') }}</n-text>
        <n-text depth="3" class="header-subtitle">{{ effectiveScope }}</n-text>
      </div>
      <n-space :size="6">
        <n-button
          v-if="canMountDirectory"
          size="small"
          quaternary
          circle
          :loading="mountingDirectory"
          :title="t('workspace.mountDirectory')"
          @click="mountLocalDirectory"
        >
          <template #icon>
            <n-icon><FolderOpenOutline /></n-icon>
          </template>
        </n-button>
        <n-button size="small" quaternary circle @click="refreshTree">
          <template #icon>
            <n-icon><Refresh /></n-icon>
          </template>
        </n-button>
      </n-space>
    </div>

    <n-scrollbar class="tree-scrollbar">
      <div class="tree-root">
        <div
          v-for="row in visibleRows"
          :key="row.key"
          class="tree-row"
          :class="{ selected: selectedPath === row.entry.path }"
          :style="{ paddingLeft: `${8 + row.depth * 16}px` }"
          @click="handleEntryClick(row.entry)"
          @contextmenu.prevent="openContextMenu($event, row.entry)"
        >
          <button
            v-if="row.entry.kind === 'directory'"
            class="twisty"
            type="button"
            @click.stop="toggleDirectory(row.entry)"
          >
            <n-icon size="13" :class="{ expanded: row.expanded }"><ChevronForward /></n-icon>
          </button>
          <span v-else class="twisty-placeholder"></span>

          <ResourceIcon
            :name="row.entry.name"
            :kind="row.entry.kind"
            :expanded="row.expanded"
            :size="18"
            class="entry-icon"
          />

          <span class="entry-name" :title="row.entry.mountSource || row.entry.path">{{ row.entry.name }}</span>
          <span
            v-if="row.entry.mount"
            class="mount-badge"
            :class="{ disconnected: row.entry.connected === false }"
            :title="row.entry.connected === false ? t('workspace.mountDisconnected') : t('workspace.mountedDirectory')"
          >
            <n-icon size="13"><LinkOutline /></n-icon>
          </span>
          <span v-if="row.entry.kind === 'file' && row.entry.sizeBytes" class="entry-size">
            {{ formatFileSize(row.entry.sizeBytes) }}
          </span>
          <div v-if="row.entry.mount" class="entry-actions" @click.stop>
            <n-button
              quaternary
              circle
              size="tiny"
              :title="t('workspace.unmountDirectory')"
              @click="confirmUnmount(row.entry)"
            >
              <template #icon><n-icon><UnlinkOutline /></n-icon></template>
            </n-button>
          </div>
          <div v-if="row.entry.kind === 'file'" class="entry-actions" @click.stop>
            <n-button quaternary circle size="tiny" :title="t('references.addWorkspaceFile')" @click="addFileReference(row.entry)">
              <template #icon><n-icon><AddCircleOutline /></n-icon></template>
            </n-button>
            <n-popconfirm @positive-click="deleteFile(row.entry)">
              <template #trigger>
                <n-button quaternary circle size="tiny" type="error" :title="t('workspace.deleteFile')">
                  <template #icon><n-icon><TrashOutline /></n-icon></template>
                </n-button>
              </template>
              {{ t('workspace.deleteFileConfirm', { name: row.entry.name }) }}
            </n-popconfirm>
          </div>
        </div>

        <div v-if="rootLoading" class="tree-hint">{{ t('workspace.loading') }}</div>
        <n-empty
          v-else-if="visibleRows.length === 0"
          :description="t('workspace.emptyDirectory')"
          size="small"
          class="empty-tree"
        />
      </div>
    </n-scrollbar>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import {
  NButton,
  NDropdown,
  NEmpty,
  NIcon,
  NScrollbar,
  NSpace,
  NText,
  NPopconfirm,
  useDialog,
  useMessage,
  type DropdownOption,
} from 'naive-ui'
import {
  ChevronForward,
  Refresh,
  AddCircleOutline,
  FolderOpenOutline,
  LinkOutline,
  TrashOutline,
  UnlinkOutline,
} from '@/components/icons'
import ResourceIcon from '@/components/common/ResourceIcon.vue'
import { useRuntimeStore } from '@/stores/runtime'
import { useWorkspaceStore } from '@/stores/workspace'
import { useCommand } from '@/composables/useCommand'
import { useI18n } from '@/composables/useI18n'
import { workspaceEntryView } from '@/stores/runtime/viewMappers'
import { workspaceFileView } from '@/stores/runtime/viewMappers'
import { workspaceApi } from '@/api/workspace'
import { selectLocalDirectory } from '@/api/desktopDialogs'
import {
  desktopWorkspaceFileActionsAvailable,
  revealWorkspaceEntry,
  saveWorkspaceFileAs,
} from '@/api/desktopWorkspaceFiles'
import { useContextReferenceStore } from '@/stores/contextReferences'
import { workspaceFileContextReference } from '@/utils/contextReferences'
import type { WorkspaceRequestContext } from '@/api/resourceTypes'
import type { FactoryFrontendEvent, WorkspaceEntry, WorkspaceScope } from '@/types/protocol'

interface TreeRow {
  key: string
  entry: WorkspaceEntry
  depth: number
  expanded: boolean
}

const emit = defineEmits<{
  selectFile: [entry: WorkspaceEntry]
}>()

const props = defineProps<{
  packageId?: string | null
  workspaceContext?: WorkspaceRequestContext | null
  fixedScope?: WorkspaceScope | null
}>()

const runtimeStore = useRuntimeStore()
const workspaceStore = useWorkspaceStore()
const commands = useCommand()
const { t } = useI18n()
const message = useMessage()
const dialog = useDialog()
const referenceStore = useContextReferenceStore()
const entriesByPath = ref<Record<string, WorkspaceEntry[]>>({})
const loadingPaths = ref<Set<string>>(new Set())
const expandedDirs = ref<Set<string>>(new Set())
const selectedPath = ref('')
const contextMenuEntry = ref<WorkspaceEntry | null>(null)
const contextMenuVisible = ref(false)
const contextMenuX = ref(0)
const contextMenuY = ref(0)
const mountingDirectory = ref(false)
const rootLoading = computed(() => loadingPaths.value.has('') && !entriesByPath.value[''])
const requestContext = computed<WorkspaceRequestContext | string | undefined>(() => (
  props.workspaceContext || props.packageId || undefined
))
const effectiveScope = computed<WorkspaceScope>(() => props.fixedScope || 'workdir')
const completedToolKeys = computed(() => (
  runtimeStore.tools
    .filter(tool => ['completed', 'failed', 'observed'].includes(tool.status))
    .map(tool => tool.activityKey)
    .sort()
    .join('\u0000')
))
const canMountDirectory = computed(() => {
  if (effectiveScope.value !== 'workdir') return false
  const context = props.workspaceContext
  return Boolean(
    context
    && context.resourceMode === 'package'
    && context.packageSessionId,
  )
})
const contextMenuOptions = computed<DropdownOption[]>(() => {
  const entry = contextMenuEntry.value
  if (!entry) return []
  const options: DropdownOption[] = [
    {
      label: entry.kind === 'directory' ? t('workspace.openDirectory') : t('workspace.openFile'),
      key: 'open',
    },
  ]
  if (desktopWorkspaceFileActionsAvailable()) {
    options.push({
      label: t('workspace.revealInFileManager'),
      key: 'reveal',
    })
    if (entry.kind === 'file') {
      options.push({
        label: t('workspace.saveAs'),
        key: 'save-as',
      })
    }
  }
  if (entry.kind === 'file') {
    options.push(
      { type: 'divider', key: 'file-actions-divider' },
      {
        label: t('references.addWorkspaceFile'),
        key: 'add-reference',
      },
    )
  }
  if (entry.mount && entry.mountId) {
    options.push(
      { type: 'divider', key: 'mount-actions-divider' },
      {
        label: t('workspace.unmountDirectory'),
        key: 'unmount',
      },
    )
  }
  return options
})

const visibleRows = computed<TreeRow[]>(() => {
  const rows: TreeRow[] = []
  appendRows('', 0, rows)
  return rows
})

function appendRows(path: string, depth: number, rows: TreeRow[]) {
  const entries = sortedEntries(entriesByPath.value[path] || [])
  for (const entry of entries) {
    const expanded = isExpanded(entry.path)
    rows.push({
      key: `${effectiveScope.value}:${entry.path}`,
      entry,
      depth,
      expanded,
    })
    if (entry.kind === 'directory' && expanded) {
      appendRows(entry.path, depth + 1, rows)
    }
  }
}

function sortedEntries(entries: WorkspaceEntry[]): WorkspaceEntry[] {
  return [...entries].sort((left, right) => {
    if (left.kind !== right.kind) return left.kind === 'directory' ? -1 : 1
    return left.name.localeCompare(right.name, 'zh-CN')
  })
}

async function loadDirectory(path: string) {
  if (loadingPaths.value.has(path)) return
  const nextLoading = new Set(loadingPaths.value)
  nextLoading.add(path)
  loadingPaths.value = nextLoading
  try {
    const event = await commands.refreshWorkspace(
      effectiveScope.value,
      path,
      requestContext.value,
    )
    entriesByPath.value = {
      ...entriesByPath.value,
      [path]: entriesFromEvent(event),
    }
  } finally {
    const done = new Set(loadingPaths.value)
    done.delete(path)
    loadingPaths.value = done
  }
}

function entriesFromEvent(event: FactoryFrontendEvent | null | undefined): WorkspaceEntry[] {
  const entries = event?.payload?.entries
  if (!Array.isArray(entries)) return []
  return entries.map(workspaceEntryView)
}

function refreshTree() {
  const expanded = Array.from(expandedDirs.value)
  entriesByPath.value = {}
  void loadDirectory('')
  expanded.forEach((path) => {
    void loadDirectory(path)
  })
}

function resetTree() {
  selectedPath.value = ''
  entriesByPath.value = {}
  expandedDirs.value = new Set()
}

function handleEntryClick(entry: WorkspaceEntry) {
  closeContextMenu()
  if (entry.kind === 'directory') {
    void toggleDirectory(entry)
    return
  }
  selectedPath.value = entry.path
  emit('selectFile', entry)
}

function openContextMenu(event: MouseEvent, entry: WorkspaceEntry) {
  contextMenuVisible.value = false
  contextMenuEntry.value = entry
  contextMenuX.value = event.clientX
  contextMenuY.value = event.clientY
  void nextTick(() => {
    contextMenuVisible.value = true
  })
}

function closeContextMenu() {
  contextMenuVisible.value = false
}

async function handleContextMenuSelect(key: string | number) {
  const entry = contextMenuEntry.value
  closeContextMenu()
  if (!entry) return
  try {
    if (key === 'open') {
      handleEntryClick(entry)
      return
    }
    if (key === 'reveal') {
      await revealWorkspaceEntry(
        effectiveScope.value,
        entry.path,
        requestContext.value,
      )
      return
    }
    if (key === 'save-as' && entry.kind === 'file') {
      const destination = await saveWorkspaceFileAs(
        effectiveScope.value,
        entry.path,
        requestContext.value,
      )
      if (destination) {
        message.success(t('workspace.fileSavedAs', { path: destination }))
      }
      return
    }
    if (key === 'add-reference' && entry.kind === 'file') {
      await addFileReference(entry)
      return
    }
    if (key === 'unmount' && entry.mountId) {
      confirmUnmount(entry)
    }
  } catch (error) {
    message.error(error instanceof Error ? error.message : String(error))
  }
}

async function mountLocalDirectory() {
  if (!canMountDirectory.value || mountingDirectory.value) return
  mountingDirectory.value = true
  try {
    const sourcePath = await selectLocalDirectory()
    if (!sourcePath) return
    const result = await workspaceApi.mountDirectory(
      sourcePath,
      props.workspaceContext,
    )
    message.success(
      result.created
        ? t('workspace.mountAdded')
        : t('workspace.mountAlreadyAdded'),
    )
    refreshTree()
  } catch (error) {
    message.error(error instanceof Error ? error.message : String(error))
  } finally {
    mountingDirectory.value = false
  }
}

function confirmUnmount(entry: WorkspaceEntry) {
  if (!entry.mountId) return
  dialog.warning({
    title: t('workspace.unmountDirectory'),
    content: t('workspace.unmountDirectoryConfirm', { name: entry.name }),
    positiveText: t('workspace.unmountDirectory'),
    negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      try {
        await workspaceApi.unmountDirectory(entry.mountId!, props.workspaceContext)
        message.success(t('workspace.mountRemoved'))
        refreshTree()
      } catch (error) {
        message.error(error instanceof Error ? error.message : String(error))
      }
    },
  })
}

async function addFileReference(entry: WorkspaceEntry) {
  const event = await workspaceApi.file(effectiveScope.value, entry.path, requestContext.value, 1_000_000)
  const reference = workspaceFileContextReference(workspaceFileView(event.payload || {}))
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

async function deleteFile(entry: WorkspaceEntry) {
  await workspaceApi.deleteFile(effectiveScope.value, entry.path, requestContext.value)
  const parentPath = entry.path.includes('/') ? entry.path.slice(0, entry.path.lastIndexOf('/')) : ''
  entriesByPath.value = {
    ...entriesByPath.value,
    [parentPath]: (entriesByPath.value[parentPath] || []).filter(item => item.path !== entry.path),
  }
  if (selectedPath.value === entry.path) selectedPath.value = ''
  message.success(t('workspace.fileDeleted'))
}

async function toggleDirectory(entry: WorkspaceEntry) {
  toggleExpanded(entry.path)
  if (isExpanded(entry.path) && !entriesByPath.value[entry.path]) {
    await loadDirectory(entry.path)
  }
}

function isExpanded(path: string): boolean {
  return expandedDirs.value.has(path)
}

function toggleExpanded(path: string): void {
  const next = new Set(expandedDirs.value)
  if (next.has(path)) {
    next.delete(path)
  } else {
    next.add(path)
  }
  expandedDirs.value = next
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

onMounted(() => {
  syncWorkspaceScope()
  void loadDirectory('')
})

watch(
  () => workspaceContextKey(requestContext.value),
  () => {
    syncWorkspaceScope()
    resetTree()
    void loadDirectory('')
  },
)

watch(completedToolKeys, (next, previous) => {
  if (next === previous) return
  refreshTree()
})

function syncWorkspaceScope() {
  if (workspaceStore.currentScope !== effectiveScope.value) {
    workspaceStore.setScope(effectiveScope.value)
  }
}

function workspaceContextKey(context: WorkspaceRequestContext | string | undefined): string {
  if (typeof context === 'string') return `package:${context}`
  if (!context) return ''
  return [
    context.resourceMode || '',
    context.packageId || '',
    context.packageSessionId || '',
    context.workspaceId || '',
    context.factorySessionId || '',
    context.createAgentSessionId || '',
    context.groupId || '',
  ].join(':')
}
</script>

<style scoped>
.workspace-explorer {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--app-surface);
}

.explorer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-sm);
  padding: var(--app-space-sm) var(--app-space-md);
  border-bottom: 1px solid var(--app-divider);
  background: var(--app-surface-muted);
}

.header-title {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.header-subtitle {
  font-size: 12px;
}

.tree-scrollbar {
  flex: 1;
  min-height: 0;
}

.tree-root {
  padding: 6px 0;
}

.tree-row {
  height: 28px;
  display: flex;
  align-items: center;
  gap: 5px;
  padding-right: 8px;
  cursor: pointer;
  color: var(--app-text);
  font-size: 13px;
  user-select: none;
  border-radius: var(--app-radius-sm);
  transition: background-color 0.12s ease;
}

.tree-row:hover {
  background: var(--app-surface-muted);
}

.tree-row.selected {
  background: var(--app-surface-pressed);
  font-weight: 500;
}

.twisty,
.twisty-placeholder {
  width: 16px;
  height: 16px;
  flex: 0 0 16px;
}

.twisty {
  border: 0;
  padding: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  color: var(--app-text-muted);
  cursor: pointer;
}

.twisty :deep(.n-icon) {
  transition: transform 0.12s ease;
}

.twisty :deep(.n-icon.expanded) {
  transform: rotate(90deg);
}

.entry-icon {
  flex: 0 0 17px;
}

.entry-name {
  min-width: 0;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mount-badge {
  display: inline-flex;
  flex: 0 0 auto;
  color: var(--app-text-muted);
}

.mount-badge.disconnected {
  color: var(--app-danger);
}

.entry-size {
  flex-shrink: 0;
  color: var(--app-text-muted);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}

.entry-actions {
  display: flex;
  flex: 0 0 auto;
  opacity: 0;
  transition: opacity var(--app-transition-fast);
}

.tree-row:hover .entry-actions,
.tree-row:focus-within .entry-actions {
  opacity: 1;
}

.tree-hint {
  padding: 16px;
  color: var(--app-text-muted);
  font-size: 13px;
}

.empty-tree {
  margin-top: 40px;
}
</style>
