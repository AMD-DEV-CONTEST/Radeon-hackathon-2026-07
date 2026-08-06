import { create } from 'zustand'
import { LOCALE_OPTIONS, type Locale, messages } from './locales'

const STORAGE_KEY = 'btx.locale'

function detectLocale(): Locale {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved && LOCALE_OPTIONS.some((l) => l.id === saved)) return saved as Locale
  } catch {
    /* ignore */
  }
  const nav = (typeof navigator !== 'undefined' ? navigator.language : 'zh').toLowerCase()
  if (nav.startsWith('ja')) return 'ja'
  if (nav.startsWith('en')) return 'en'
  return 'zh'
}

function applyDocumentLang(locale: Locale) {
  if (typeof document === 'undefined') return
  document.documentElement.lang = locale === 'zh' ? 'zh-CN' : locale === 'ja' ? 'ja' : 'en'
}

type LocaleState = {
  locale: Locale
  setLocale: (locale: Locale) => void
}

export const useLocaleStore = create<LocaleState>((set) => {
  const initial = typeof window === 'undefined' ? ('zh' as Locale) : detectLocale()
  if (typeof window !== 'undefined') applyDocumentLang(initial)
  return {
    locale: initial,
    setLocale: (locale) => {
      try {
        localStorage.setItem(STORAGE_KEY, locale)
      } catch {
        /* ignore */
      }
      applyDocumentLang(locale)
      set({ locale })
    },
  }
})

export function getMessages(locale: Locale = useLocaleStore.getState().locale) {
  return messages[locale] ?? messages.zh
}
