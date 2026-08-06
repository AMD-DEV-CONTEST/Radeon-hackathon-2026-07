import { useCallback, useState } from 'react'
import {
  B601_ACTION_GUIDE,
  makeActivityEntry,
  type B601ActivityEntry,
} from '../components/b601/B601ActivityPanel'

export type B601ActionKey = keyof typeof B601_ACTION_GUIDE

export function useB601Activity(max = 12) {
  const [entries, setEntries] = useState<B601ActivityEntry[]>([])

  const log = useCallback(
    (key: B601ActionKey, extra?: string) => {
      setEntries((prev) => [...prev.slice(-(max - 1)), makeActivityEntry(key, extra)])
    },
    [max],
  )

  return { entries, log }
}
