import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  modelPoolApi,
  type LocalModelDefaultRole,
  type LocalModelDefaults,
  type ModelPoolProfile,
} from '@/api/modelPool'

function emptyDefaults(): LocalModelDefaults {
  return {
    main: null,
    task: null,
    compression: null,
    embedding: null,
    image_generation: null,
  }
}

export const useModelPoolStore = defineStore('modelPool', () => {
  const profiles = ref<ModelPoolProfile[]>([])
  const defaults = ref<LocalModelDefaults>(emptyDefaults())
  const loaded = ref(false)
  const loading = ref(false)
  const error = ref('')
  let refreshPromise: Promise<void> | null = null

  function profile(profileId: string | null | undefined): ModelPoolProfile | null {
    if (!profileId) return null
    return profiles.value.find(item => item.profile_id === profileId) || null
  }

  async function refresh(): Promise<void> {
    if (refreshPromise) return refreshPromise
    loading.value = true
    refreshPromise = Promise.all([modelPoolApi.profiles(), modelPoolApi.defaults()])
      .then(([profileResponse, defaultResponse]) => {
        profiles.value = profileResponse.profiles
        defaults.value = defaultResponse.defaults
        loaded.value = true
        error.value = ''
      })
      .catch((reason: unknown) => {
        error.value = reason instanceof Error ? reason.message : String(reason)
        throw reason
      })
      .finally(() => {
        loading.value = false
        refreshPromise = null
      })
    return refreshPromise
  }

  async function ensureLoaded(): Promise<void> {
    if (!loaded.value) await refresh()
  }

  function upsertProfile(value: ModelPoolProfile): void {
    const index = profiles.value.findIndex(item => item.profile_id === value.profile_id)
    if (index < 0) profiles.value = [...profiles.value, value]
    else profiles.value = profiles.value.map((item, itemIndex) => itemIndex === index ? value : item)
  }

  function removeProfile(profileId: string): void {
    profiles.value = profiles.value.filter(item => item.profile_id !== profileId)
    for (const role of Object.keys(defaults.value) as LocalModelDefaultRole[]) {
      if (defaults.value[role] === profileId) defaults.value[role] = null
    }
  }

  function setDefault(role: LocalModelDefaultRole, profileId: string | null): void {
    defaults.value = { ...defaults.value, [role]: profileId }
  }

  return {
    profiles,
    defaults,
    loaded,
    loading,
    error,
    profile,
    refresh,
    ensureLoaded,
    upsertProfile,
    removeProfile,
    setDefault,
  }
})
