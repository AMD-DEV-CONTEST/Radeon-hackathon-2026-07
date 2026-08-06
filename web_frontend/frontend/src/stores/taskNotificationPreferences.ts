import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

export type TaskNotificationCategory = 'conversation' | 'agentGroup' | 'scheduler'

interface StoredTaskNotificationPreferences {
  enabled: boolean
  categories: Record<TaskNotificationCategory, boolean>
}

const STORAGE_KEY = 'fast-agent-factory.taskNotifications'

const DEFAULT_PREFERENCES: StoredTaskNotificationPreferences = {
  enabled: true,
  categories: {
    conversation: true,
    agentGroup: true,
    scheduler: true,
  },
}

function readPreferences(): StoredTaskNotificationPreferences {
  if (typeof window === 'undefined') return structuredClone(DEFAULT_PREFERENCES)
  try {
    const stored = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || '{}')
    const storedCategories = stored?.categories && typeof stored.categories === 'object'
      ? stored.categories
      : {}
    return {
      enabled: stored?.enabled !== false,
      categories: {
        conversation: storedCategories.conversation !== false,
        agentGroup: storedCategories.agentGroup !== false,
        scheduler: storedCategories.scheduler !== false,
      },
    }
  } catch {
    return structuredClone(DEFAULT_PREFERENCES)
  }
}

function writePreferences(preferences: StoredTaskNotificationPreferences): void {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(preferences))
}

export const useTaskNotificationPreferencesStore = defineStore('taskNotificationPreferences', () => {
  const stored = readPreferences()
  const enabled = ref(stored.enabled)
  const categories = ref<Record<TaskNotificationCategory, boolean>>(stored.categories)

  const active = computed(() => enabled.value && Object.values(categories.value).some(Boolean))

  function setEnabled(value: boolean): void {
    enabled.value = value
    persist()
  }

  function setCategoryEnabled(category: TaskNotificationCategory, value: boolean): void {
    categories.value = {
      ...categories.value,
      [category]: value,
    }
    persist()
  }

  function isCategoryEnabled(category: TaskNotificationCategory): boolean {
    return enabled.value && categories.value[category]
  }

  function persist(): void {
    writePreferences({
      enabled: enabled.value,
      categories: { ...categories.value },
    })
  }

  return {
    enabled,
    categories,
    active,
    setEnabled,
    setCategoryEnabled,
    isCategoryEnabled,
  }
})
