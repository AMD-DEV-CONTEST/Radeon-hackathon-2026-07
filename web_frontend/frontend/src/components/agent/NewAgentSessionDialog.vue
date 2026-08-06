<template>
  <n-modal
    :show="show"
    preset="card"
    class="new-agent-session-modal"
    :closable="false"
    :mask-closable="false"
    :close-on-esc="false"
  >
    <template #header>
      <div class="new-session-header">
        <span>{{ dialogTitle }}</span>
        <n-button
          quaternary
          circle
          :disabled="!dialogClosable"
          :aria-label="t('common.close')"
          @click="closeDialog"
        >
          <template #icon><n-icon><CloseOutline /></n-icon></template>
        </n-button>
      </div>
    </template>

    <div v-if="directoryStep" class="directory-picker">
      <div class="directory-picker-toolbar">
        <n-button
          quaternary
          :disabled="!parentPath || directoryLoading"
          @click="parentPath && loadDirectory(parentPath)"
        >
          {{ t('workspace.parentDirectory') }}
        </n-button>
        <n-text class="directory-picker-path" :title="currentPath">
          {{ currentPath || t('workspace.selectDirectoryRoot') }}
        </n-text>
      </div>

      <n-spin :show="directoryLoading">
        <n-list bordered clickable class="directory-picker-list">
          <n-list-item
            v-for="directory in visibleDirectories"
            :key="directory.path"
            @dblclick="loadDirectory(directory.path)"
          >
            <button
              type="button"
              class="directory-row"
              :class="{ selected: selectedDirectoryPath === directory.path }"
              @click="selectedDirectoryPath = directory.path"
              @dblclick.stop="loadDirectory(directory.path)"
            >
              <n-icon><FolderOutline /></n-icon>
              <span>{{ directory.name }}</span>
            </button>
          </n-list-item>
        </n-list>
      </n-spin>
    </div>

    <div v-else class="new-session-options">
      <button type="button" class="new-session-option" @click="selectWorkspace(null)">
        <strong>{{ t('sessions.newIndependentTask') }}</strong>
        <span>{{ t('sessions.newIndependentTaskDescription') }}</span>
      </button>

      <section class="new-session-option shared-workspace-option">
        <div>
          <strong>{{ t('sessions.newInWorkspace') }}</strong>
          <span>{{ t('sessions.newInWorkspaceDescription') }}</span>
        </div>
        <n-select
          v-model:value="selectedWorkspaceId"
          :options="workspaceOptions"
          filterable
          :placeholder="t('sessions.selectWorkspace')"
        />
        <div class="shared-workspace-actions">
          <n-button
            secondary
            :loading="linkedWorkspaceBusy"
            @click="chooseLinkedWorkspace"
          >
            {{ t('sessions.selectLocalFolder') }}
          </n-button>
          <n-button
            type="primary"
            :disabled="!selectedWorkspaceId"
            @click="selectedWorkspaceId && selectWorkspace(selectedWorkspaceId)"
          >
            {{ t('sessions.createInWorkspace') }}
          </n-button>
        </div>
      </section>
    </div>

    <template #footer>
      <div v-if="directoryStep" class="new-session-footer">
        <n-button :disabled="linkedWorkspaceBusy" @click="leaveDirectoryStep">
          {{ t('common.cancel') }}
        </n-button>
        <n-button
          type="primary"
          :loading="creatingLinkedWorkspace"
          :disabled="directoryLoading || (!selectedDirectoryPath && !currentPath)"
          @click="selectDirectory"
        >
          {{ t('workspace.selectThisDirectory') }}
        </n-button>
      </div>
      <div v-else class="new-session-footer">
        <n-button :disabled="!dialogClosable" @click="closeDialog">
          {{ t('common.cancel') }}
        </n-button>
      </div>
    </template>
  </n-modal>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  NButton,
  NIcon,
  NList,
  NListItem,
  NModal,
  NSelect,
  NSpin,
  NText,
  useMessage,
} from 'naive-ui'
import { CloseOutline, FolderOutline } from '@/components/icons'
import {
  NativeDirectoryPickerUnavailableError,
  selectLocalDirectory,
} from '@/api/desktopDialogs'
import {
  workspaceApi,
  type WorkspaceDirectoryView,
  type WorkspaceProjectView,
} from '@/api/workspace'
import { useI18n } from '@/composables/useI18n'

const props = defineProps<{
  show: boolean
  packageId: string
  initialWorkspaceId?: string | null
}>()
const emit = defineEmits<{
  'update:show': [show: boolean]
  create: [workspaceId: string | null]
}>()
const { t } = useI18n()
const message = useMessage()
const workspaces = ref<WorkspaceProjectView[]>([])
const selectedWorkspaceId = ref<string | null>(null)
const selectingLinkedWorkspace = ref(false)
const creatingLinkedWorkspace = ref(false)
const directoryStep = ref(false)
const directoryLoading = ref(false)
const directoryRoots = ref<WorkspaceDirectoryView[]>([])
const directories = ref<WorkspaceDirectoryView[]>([])
const currentPath = ref('')
const parentPath = ref<string | null>(null)
const selectedDirectoryPath = ref('')
const linkedWorkspaceBusy = computed(() => (
  selectingLinkedWorkspace.value || creatingLinkedWorkspace.value
))
const dialogClosable = computed(() => (
  !linkedWorkspaceBusy.value && !directoryLoading.value
))
const dialogTitle = computed(() => (
  directoryStep.value ? t('workspace.selectServerDirectory') : t('sessions.createTitle')
))
const visibleDirectories = computed(() => (
  currentPath.value ? directories.value : directoryRoots.value
))
const workspaceOptions = computed(() => workspaces.value
  .filter(workspace => workspace.mode === 'project')
  .map(workspace => ({
    label: `${workspace.title} — ${workspace.workdir_root}`,
    value: workspace.workspace_id,
  })))

watch(
  () => props.show,
  show => {
    if (!show) {
      directoryStep.value = false
      return
    }
    selectedWorkspaceId.value = props.initialWorkspaceId || null
    void refreshWorkspaces()
  },
)

async function refreshWorkspaces() {
  try {
    workspaces.value = (await workspaceApi.projects()).workspaces
  } catch (error) {
    showError(error)
  }
}

function selectWorkspace(workspaceId: string | null) {
  emit('create', workspaceId)
  emit('update:show', false)
}

async function chooseLinkedWorkspace() {
  if (linkedWorkspaceBusy.value) return
  selectingLinkedWorkspace.value = true
  try {
    const sourcePath = await selectLocalDirectory()
    if (sourcePath) await registerLinkedWorkspace(sourcePath)
  } catch (error) {
    if (error instanceof NativeDirectoryPickerUnavailableError) {
      directoryStep.value = true
      await loadDirectoryRoots()
    } else {
      showError(error)
    }
  } finally {
    selectingLinkedWorkspace.value = false
  }
}

async function loadDirectoryRoots() {
  directoryLoading.value = true
  selectedDirectoryPath.value = ''
  currentPath.value = ''
  parentPath.value = null
  try {
    directoryRoots.value = (await workspaceApi.directoryRoots()).roots
    directories.value = []
  } catch (error) {
    showError(error)
  } finally {
    directoryLoading.value = false
  }
}

async function loadDirectory(path: string) {
  directoryLoading.value = true
  selectedDirectoryPath.value = ''
  try {
    const listing = await workspaceApi.directories(path)
    currentPath.value = listing.path
    parentPath.value = listing.parent
    directories.value = listing.directories
  } catch (error) {
    showError(error)
  } finally {
    directoryLoading.value = false
  }
}

async function selectDirectory() {
  const path = selectedDirectoryPath.value || currentPath.value
  if (!path) return
  await registerLinkedWorkspace(path)
}

function leaveDirectoryStep() {
  if (linkedWorkspaceBusy.value) return
  directoryStep.value = false
}

function closeDialog() {
  if (dialogClosable.value) emit('update:show', false)
}

async function registerLinkedWorkspace(sourcePath: string) {
  creatingLinkedWorkspace.value = true
  try {
    const response = await workspaceApi.createProject({
      title: sourcePath.split(/[\\/]/).filter(Boolean).at(-1) || t('sessions.sharedWorkspace'),
      mode: 'project',
      root_kind: 'linked',
      workdir_root: sourcePath,
      owner_package_id: props.packageId,
    })
    workspaces.value = [
      response.workspace,
      ...workspaces.value.filter(
        workspace => workspace.workspace_id !== response.workspace.workspace_id,
      ),
    ]
    selectWorkspace(response.workspace.workspace_id)
  } catch (error) {
    showError(error)
  } finally {
    creatingLinkedWorkspace.value = false
  }
}

function showError(error: unknown) {
  message.error(error instanceof Error ? error.message : String(error))
}
</script>

<style scoped>
:global(.new-agent-session-modal) {
  width: min(620px, calc(100vw - 32px));
}

.new-session-options {
  display: grid;
  gap: var(--app-space-md);
}

.new-session-header {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-md);
}

.new-session-option {
  width: 100%;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
  background: var(--app-surface);
  color: var(--app-text);
  padding: var(--app-space-lg);
  display: grid;
  gap: var(--app-space-xs);
  text-align: left;
}

button.new-session-option {
  cursor: pointer;
  transition:
    border-color var(--app-transition-fast),
    transform var(--app-transition-fast);
}

button.new-session-option:hover {
  border-color: var(--app-text);
  transform: translateY(-1px);
}

.new-session-option span {
  color: var(--app-text-muted);
  font-size: var(--app-font-sm);
}

.shared-workspace-option {
  gap: var(--app-space-md);
}

.shared-workspace-option > div:first-child {
  display: grid;
  gap: var(--app-space-xs);
}

.shared-workspace-actions,
.new-session-footer {
  display: flex;
  justify-content: flex-end;
  gap: var(--app-space-sm);
}

.directory-picker-toolbar {
  display: flex;
  align-items: center;
  gap: var(--app-space-sm);
  margin-bottom: var(--app-space-md);
}

.directory-picker-path {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.directory-picker-list {
  height: min(420px, 55vh);
  overflow: auto;
}

.directory-row {
  width: 100%;
  border: 0;
  border-radius: var(--app-radius-sm);
  background: transparent;
  color: var(--app-text);
  display: flex;
  align-items: center;
  gap: var(--app-space-sm);
  padding: var(--app-space-xs);
  text-align: left;
  cursor: pointer;
}

.directory-row.selected {
  background: var(--app-surface-hover);
}
</style>
