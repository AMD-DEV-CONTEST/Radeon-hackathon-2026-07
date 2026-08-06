import { computed } from 'vue'
import { localeOptions, translate, type I18nKey } from '@/i18n'
import { useUiStore } from '@/stores/ui'

export function useI18n() {
  const uiStore = useUiStore()
  const locale = computed(() => uiStore.locale)

  function t(key: I18nKey, params?: Record<string, string | number>): string {
    return translate(locale.value, key, params)
  }

  return {
    locale,
    localeOptions,
    t,
  }
}
