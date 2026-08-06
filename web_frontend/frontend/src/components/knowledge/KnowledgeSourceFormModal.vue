<template>
  <n-modal
    v-model:show="show"
    preset="card"
    :title="t('knowledge.formTitle')"
    :closable="!submitting"
    :mask-closable="!submitting"
    :close-on-esc="!submitting"
    style="width: min(560px, calc(100vw - 32px)); max-height: min(760px, calc(100vh - 48px))"
    content-style="min-height: 0; overflow-y: auto"
  >
    <n-form ref="formRef" :model="formData" :rules="rules">
      <n-form-item :label="t('knowledge.kind')" path="kind">
        <n-select v-model:value="formData.kind" :options="kindOptions" @update:value="handleKindChange" />
      </n-form-item>

      <n-form-item :label="t('knowledge.displayName')" path="display_name">
        <n-input v-model:value="formData.display_name" :placeholder="t('knowledge.displayNamePlaceholder')" />
      </n-form-item>

      <n-form-item
        v-if="usesUpload"
        :label="t('knowledge.fileContent')"
        required
        :validation-status="uploadValidationError ? 'error' : undefined"
        :feedback="uploadValidationError ? t('knowledge.validateFiles') : undefined"
      >
        <div class="upload-field">
          <n-alert v-if="capabilitiesError" type="error" :title="t('knowledge.capabilitiesUnavailable')">
            {{ capabilitiesError }}
          </n-alert>
          <n-alert v-else type="info" :title="t('knowledge.supportedFormats')">
            <div class="format-groups">
              <n-tag
                v-for="group in knowledgeFormatGroups"
                :key="group.group_id"
                size="small"
                :bordered="false"
              >
                {{ formatGroupLabel(group.group_id) }}
              </n-tag>
            </div>
          </n-alert>
          <n-alert v-if="rejectedFileNames.length" type="warning" :title="t('knowledge.unsupportedFilesRejected')">
            {{ rejectedFileNames.join(', ') }}
          </n-alert>
          <div
            class="upload-zone"
            @dragover.prevent
            @drop.prevent="handleDrop"
          >
            <n-text>{{ uploadTitle }}</n-text>
            <n-text depth="3" class="upload-hint">
              {{ t('knowledge.uploadHint') }}
            </n-text>
            <n-space>
              <n-button :disabled="!capabilities" @click="openFilePicker">{{ t('knowledge.selectFile') }}</n-button>
              <n-button :disabled="!capabilities" @click="openFolderPicker">{{ t('knowledge.selectFolder') }}</n-button>
            </n-space>
          </div>
          <input
            ref="fileInputRef"
            class="native-input"
            type="file"
            multiple
            :accept="fileAccept"
            @change="handleFileInput"
          />
          <input
            ref="folderInputRef"
            class="native-input"
            type="file"
            multiple
            :accept="fileAccept"
            webkitdirectory
            directory
            @change="handleFileInput"
          />
          <div v-if="selectedFiles.length" class="selected-files">
            <n-text depth="3">{{ t('knowledge.filesSelected', { count: selectedFiles.length }) }}</n-text>
            <div
              v-for="item in selectedFiles.slice(0, 8)"
              :key="item.relativePath"
              class="selected-file"
              :title="item.relativePath"
            >
              {{ item.relativePath }}
            </div>
            <n-text v-if="selectedFiles.length > 8" depth="3" class="upload-hint">
              {{ t('knowledge.moreFiles', { count: selectedFiles.length - 8 }) }}
            </n-text>
          </div>
        </div>
      </n-form-item>

      <n-form-item v-if="formData.kind === 'url'" :label="t('knowledge.urlAddress')" path="uri">
        <n-input v-model:value="formData.uri" placeholder="https://example.com/docs" />
      </n-form-item>

      <n-form-item v-if="formData.kind === 'note'" :label="t('knowledge.content')" path="content">
        <n-input
          v-model:value="formData.content"
          type="textarea"
          :rows="6"
          :placeholder="t('knowledge.notePlaceholder')"
        />
      </n-form-item>

      <n-form-item :label="t('knowledge.mountMode')" path="mount_mode">
        <n-radio-group v-model:value="formData.mount_mode">
          <n-radio value="index_only">{{ t('knowledge.indexOnly') }}</n-radio>
          <n-radio value="rag">{{ t('knowledge.rag') }}</n-radio>
        </n-radio-group>
      </n-form-item>

      <n-collapse-transition :show="formData.mount_mode === 'rag'">
        <div class="rag-options">
          <n-form-item :label="t('knowledge.chunkingStrategy')">
            <n-select v-model:value="chunking.splitter" :options="splitterOptions" />
          </n-form-item>
          <div class="chunk-grid">
            <n-form-item :label="t('knowledge.chunkSize')">
              <n-input-number v-model:value="chunking.chunkSize" :min="100" :max="8000" :step="100" />
            </n-form-item>
            <n-form-item :label="t('knowledge.chunkOverlap')">
              <n-input-number v-model:value="chunking.chunkOverlap" :min="0" :max="2000" :step="20" />
            </n-form-item>
          </div>
        </div>
      </n-collapse-transition>
    </n-form>

    <template #footer>
      <n-space justify="end">
        <n-button :disabled="submitting" @click="show = false">{{ t('common.cancel') }}</n-button>
        <n-button type="primary" :loading="submitting" @click="handleSubmit">
          {{ t('common.add') }}
        </n-button>
      </n-space>
    </template>
  </n-modal>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import {
  NAlert,
  NButton,
  NCollapseTransition,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NModal,
  NRadio,
  NRadioGroup,
  NSelect,
  NSpace,
  NTag,
  NText,
} from 'naive-ui'
import type { FormInst, FormRules } from 'naive-ui'
import type { KnowledgeSourceInput, KnowledgeUploadFile } from '@/api/resourceTypes'
import type { FileFormatGroupCapabilities } from '@/api/files'
import { useI18n } from '@/composables/useI18n'
import { useFileCapabilities } from '@/composables/useFileCapabilities'
import { requiredTextRule, validateForm } from '@/utils/formValidation'
import type { I18nKey } from '@/i18n'

type SourceKind = 'folder' | 'file' | 'url' | 'note'
type SplitterKind = 'recursive' | 'markdown' | 'code' | 'json'

const DEFAULT_SOURCE_KIND: SourceKind = 'file'

interface FileSystemEntryLike {
  isFile: boolean
  isDirectory: boolean
  name: string
}

interface FileSystemFileEntryLike extends FileSystemEntryLike {
  file: (callback: (file: File) => void) => void
}

interface FileSystemDirectoryEntryLike extends FileSystemEntryLike {
  createReader: () => {
    readEntries: (callback: (entries: FileSystemEntryLike[]) => void) => void
  }
}

interface KnowledgeSourceFormDraft {
  kind: SourceKind
  display_name: string
  uri: string
  content: string
  mount_mode: 'index_only' | 'rag'
}

const props = defineProps<{
  show: boolean
  submitting?: boolean
}>()

const emit = defineEmits<{
  'update:show': [value: boolean]
  submit: [data: KnowledgeSourceInput]
}>()

const show = computed({
  get: () => props.show,
  set: (value) => emit('update:show', value),
})
const submitting = computed(() => props.submitting === true)

const formRef = ref<FormInst | null>(null)
const { t } = useI18n()
const {
  capabilities,
  knowledgeExtensions: acceptedExtensions,
  error: capabilitiesError,
  load: loadFileCapabilities,
} = useFileCapabilities()
const fileInputRef = ref<HTMLInputElement | null>(null)
const folderInputRef = ref<HTMLInputElement | null>(null)
const selectedFiles = ref<KnowledgeUploadFile[]>([])
const uploadValidationVisible = ref(false)
const rejectedFileNames = ref<string[]>([])
const formData = ref<KnowledgeSourceFormDraft>({
  kind: DEFAULT_SOURCE_KIND,
  display_name: '',
  uri: '',
  content: '',
  mount_mode: 'rag',
})
const chunking = ref({
  splitter: 'recursive' as SplitterKind,
  chunkSize: 800,
  chunkOverlap: 120,
})

const kindOptions = computed(() => [
  { label: t('knowledge.uploadFile'), value: 'file' },
  { label: t('knowledge.uploadFolder'), value: 'folder' },
  { label: 'URL', value: 'url' },
  { label: t('knowledge.note'), value: 'note' },
])

const splitterOptions = computed(() => [
  { label: t('knowledge.splitterRecursive'), value: 'recursive' },
  { label: t('knowledge.splitterMarkdown'), value: 'markdown' },
  { label: t('knowledge.splitterCode'), value: 'code' },
  { label: t('knowledge.splitterJson'), value: 'json' },
])

const usesUpload = computed(() => formData.value.kind === 'folder' || formData.value.kind === 'file')
const fileAccept = computed(() => capabilities.value?.knowledge_accept || '')
const knowledgeFormatGroups = computed(() => (
  capabilities.value?.format_groups.filter((group) => group.knowledge_extensions.length > 0) || []
))
const uploadTitle = computed(() => (formData.value.kind === 'folder' ? t('knowledge.dropFolder') : t('knowledge.dropFile')))
const uploadValidationError = computed(() => (
  uploadValidationVisible.value
  && usesUpload.value
  && selectedFiles.value.length === 0
))

const rules = computed<FormRules>(() => ({
  display_name: [
    requiredTextRule(t('knowledge.validateDisplayName')),
  ],
  uri: [
    {
      required: formData.value.kind === 'url',
      validator: (_rule, value) => {
        if (formData.value.kind !== 'url') return true
        return isValidUrl(value) ? true : new Error(t('knowledge.validateUrl'))
      },
      trigger: 'blur',
    },
  ],
  content: [
    {
      required: formData.value.kind === 'note',
      validator: () => {
        if (formData.value.kind !== 'note') return true
        return formData.value.content.trim() ? true : new Error(t('knowledge.validateNote'))
      },
      trigger: 'blur',
    },
  ],
}))

function handleKindChange() {
  uploadValidationVisible.value = false
  selectedFiles.value = []
  rejectedFileNames.value = []
  formData.value.uri = ''
  formData.value.content = ''
}

function openFilePicker() {
  fileInputRef.value?.click()
}

function openFolderPicker() {
  folderInputRef.value?.click()
}

function handleFileInput(event: Event) {
  const input = event.target as HTMLInputElement
  addFiles(Array.from(input.files || []).map((file) => ({
    file,
    relativePath: (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name,
  })))
  input.value = ''
}

async function handleDrop(event: DragEvent) {
  const items = Array.from(event.dataTransfer?.items || [])
  if (items.length) {
    const files = await filesFromDataTransferItems(items)
    addFiles(files)
    return
  }
  addFiles(Array.from(event.dataTransfer?.files || []).map((file) => ({ file, relativePath: file.name })))
}

function addFiles(files: KnowledgeUploadFile[]) {
  const next = new Map(selectedFiles.value.map((item) => [item.relativePath, item]))
  const rejected: string[] = []
  files.forEach((item) => {
    if (!isAcceptedFile(item.file)) {
      rejected.push(item.relativePath || item.file.name)
    } else if (item.file.size >= 0 && item.relativePath) {
      next.set(item.relativePath, item)
    }
  })
  selectedFiles.value = Array.from(next.values())
  rejectedFileNames.value = rejected
}

function isAcceptedFile(file: File): boolean {
  const name = file.name.toLowerCase()
  const dotIndex = name.lastIndexOf('.')
  if (dotIndex < 0) return false
  return acceptedExtensions.value.has(name.slice(dotIndex))
}

async function filesFromDataTransferItems(items: DataTransferItem[]): Promise<KnowledgeUploadFile[]> {
  const collected: KnowledgeUploadFile[] = []
  for (const item of items) {
    const entry = (item as DataTransferItem & { webkitGetAsEntry?: () => FileSystemEntryLike | null }).webkitGetAsEntry?.()
    if (entry) {
      collected.push(...await filesFromEntry(entry, ''))
      continue
    }
    const file = item.getAsFile()
    if (file) collected.push({ file, relativePath: file.name })
  }
  return collected
}

async function filesFromEntry(entry: FileSystemEntryLike, prefix: string): Promise<KnowledgeUploadFile[]> {
  if (entry.isFile) {
    const file = await fileFromEntry(entry as FileSystemFileEntryLike)
    return [{ file, relativePath: [prefix, file.name].filter(Boolean).join('/') }]
  }
  if (!entry.isDirectory) return []
  const directory = entry as FileSystemDirectoryEntryLike
  const entries = await readDirectoryEntries(directory)
  const nextPrefix = [prefix, directory.name].filter(Boolean).join('/')
  const groups = await Promise.all(entries.map((item) => filesFromEntry(item, nextPrefix)))
  return groups.flat()
}

function fileFromEntry(entry: FileSystemFileEntryLike): Promise<File> {
  return new Promise((resolve) => entry.file(resolve))
}

function readDirectoryEntries(entry: FileSystemDirectoryEntryLike): Promise<FileSystemEntryLike[]> {
  const reader = entry.createReader()
  const entries: FileSystemEntryLike[] = []
  return new Promise((resolve) => {
    const readBatch = () => {
      reader.readEntries((batch) => {
        if (!batch.length) {
          resolve(entries)
          return
        }
        entries.push(...batch)
        readBatch()
      })
    }
    readBatch()
  })
}

async function handleSubmit() {
  if (submitting.value) return
  uploadValidationVisible.value = true
  const valid = await validateForm(formRef.value)
  if (!valid || uploadValidationError.value) return
  emit('submit', buildSourceInput())
}

watch(show, (visible) => {
  if (!visible) resetForm()
})

onMounted(() => {
  void loadFileCapabilities()
})

const FORMAT_GROUP_LABELS: Record<string, I18nKey> = {
  documents: 'files.group.documents',
  spreadsheets: 'files.group.spreadsheets',
  presentations: 'files.group.presentations',
  text_code: 'files.group.textCode',
  email_ebook: 'files.group.emailEbook',
  images: 'files.group.images',
}

function formatGroupLabel(groupId: FileFormatGroupCapabilities['group_id']): string {
  return t(FORMAT_GROUP_LABELS[groupId] || 'files.group.other')
}

function buildSourceInput(): KnowledgeSourceInput {
  const base: KnowledgeSourceInput = {
    kind: formData.value.kind,
    display_name: formData.value.display_name.trim(),
    uri: formData.value.uri.trim(),
    content: formData.value.content,
    mount_mode: formData.value.mount_mode,
    ingestion_plan: formData.value.mount_mode === 'rag'
      ? {
          planner: 'system_default',
          default_splitter: chunking.value.splitter,
          default_chunk_size: chunking.value.chunkSize,
          default_chunk_overlap: chunking.value.chunkOverlap,
          rules: [],
        }
      : undefined,
  }
  if (usesUpload.value) {
    base.uri = ''
    base.files = selectedFiles.value
  }
  if (formData.value.kind === 'note') {
    base.uri = formData.value.content
  }
  if (formData.value.kind === 'url') {
    base.kind = 'url'
  }
  return base
}

function resetForm() {
  formData.value = {
    kind: DEFAULT_SOURCE_KIND,
    display_name: '',
    uri: '',
    content: '',
    mount_mode: 'rag',
  }
  chunking.value = {
    splitter: 'recursive',
    chunkSize: 800,
    chunkOverlap: 120,
  }
  uploadValidationVisible.value = false
  selectedFiles.value = []
  rejectedFileNames.value = []
}

function isValidUrl(value: string): boolean {
  try {
    const url = new URL(value)
    return url.protocol === 'http:' || url.protocol === 'https:'
  } catch {
    return false
  }
}
</script>

<style scoped>
.upload-field {
  width: 100%;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.format-groups {
  display: flex;
  flex-wrap: wrap;
  gap: var(--app-space-xs);
}

.upload-zone {
  box-sizing: border-box;
  width: 100%;
  min-height: 112px;
  border: 1px dashed var(--app-border-hover);
  border-radius: var(--app-radius-md);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  background: var(--app-surface-muted);
  transition: border-color 0.15s ease, background-color 0.15s ease;
}

.upload-zone:hover {
  border-color: var(--app-text);
  background: var(--app-surface-hover);
}

.upload-hint {
  font-size: 12px;
}

.native-input {
  display: none;
}

.selected-files {
  box-sizing: border-box;
  width: 100%;
  min-width: 0;
  padding: 10px 12px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  display: flex;
  flex-direction: column;
  gap: 4px;
  background: var(--app-surface-muted);
  max-height: 132px;
  overflow-y: auto;
}

.selected-file {
  font-size: 12px;
  color: var(--app-text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rag-options {
  padding: 10px 12px 0;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  margin-bottom: 12px;
  background: var(--app-surface-muted);
}

.chunk-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

@media (max-width: 560px) {
  .chunk-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
