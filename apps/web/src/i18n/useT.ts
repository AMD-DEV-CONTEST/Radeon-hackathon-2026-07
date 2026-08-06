import { useCallback } from 'react'
import { useLocaleStore, getMessages } from './store'
import type { MessageTree } from './locales'

type Path<T> = T extends string
  ? never
  : {
      [K in keyof T & string]: T[K] extends string
        ? K
        : T[K] extends Record<string, unknown>
          ? `${K}.${Path<T[K]>}`
          : never
    }[keyof T & string]

export type MessageKey = Path<MessageTree>

function lookup(tree: MessageTree, key: string): string {
  const parts = key.split('.')
  let cur: unknown = tree
  for (const p of parts) {
    if (cur == null || typeof cur !== 'object') return key
    cur = (cur as Record<string, unknown>)[p]
  }
  return typeof cur === 'string' ? cur : key
}

export function useT() {
  const locale = useLocaleStore((s) => s.locale)
  return useCallback(
    (key: MessageKey | string) => lookup(getMessages(locale), key),
    [locale],
  )
}

export function useLocale() {
  return useLocaleStore((s) => s.locale)
}
