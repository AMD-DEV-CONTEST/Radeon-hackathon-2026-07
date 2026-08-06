import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { ResourceTarget } from '@/types/resourceTarget'

export const useResourceTargetStore = defineStore('resourceTarget', () => {
  const explicitTarget = ref<ResourceTarget | null>(null)
  const inferredContextKey = ref<string | null>(null)

  function synchronizeContext(contextKey: string): void {
    if (inferredContextKey.value && inferredContextKey.value !== contextKey) {
      explicitTarget.value = null
    }
    inferredContextKey.value = contextKey
  }

  function selectTarget(target: ResourceTarget | null): void {
    explicitTarget.value = target
  }

  return {
    explicitTarget,
    inferredContextKey,
    selectTarget,
    synchronizeContext,
  }
})
