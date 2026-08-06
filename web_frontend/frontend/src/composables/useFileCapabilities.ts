import { computed, readonly, ref } from 'vue'
import { fileApi, type FileProcessingCapabilities } from '@/api/files'

const capabilities = ref<FileProcessingCapabilities | null>(null)
const loading = ref(false)
const error = ref('')
let pendingRequest: Promise<FileProcessingCapabilities> | null = null

export function useFileCapabilities() {
  async function load(): Promise<FileProcessingCapabilities | null> {
    if (capabilities.value) return capabilities.value
    if (!pendingRequest) {
      loading.value = true
      error.value = ''
      pendingRequest = fileApi.capabilities()
        .then((value) => {
          capabilities.value = value
          return value
        })
        .catch((reason) => {
          error.value = reason instanceof Error ? reason.message : String(reason)
          throw reason
        })
        .finally(() => {
          loading.value = false
          pendingRequest = null
        })
    }
    try {
      return await pendingRequest
    } catch {
      return null
    }
  }

  return {
    capabilities: readonly(capabilities),
    loading: readonly(loading),
    error: readonly(error),
    attachmentExtensions: computed(() => new Set(capabilities.value?.attachment_extensions || [])),
    knowledgeExtensions: computed(() => new Set(capabilities.value?.knowledge_extensions || [])),
    load,
  }
}
