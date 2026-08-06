import { useCallback, useEffect, useSyncExternalStore } from 'react'
import { reachyRandomMotionStore } from '../lib/reachyRandomMotionStore'

export type { RandomPoolItem } from '../lib/reachyRandomMotionStore'

export function useReachyRandomMotion(daemonOnline: boolean) {
  const snapshot = useSyncExternalStore(
    reachyRandomMotionStore.subscribe,
    reachyRandomMotionStore.getSnapshot,
    reachyRandomMotionStore.getSnapshot,
  )

  const stop = useCallback(() => {
    reachyRandomMotionStore.stop()
  }, [])

  const start = useCallback(() => {
    void reachyRandomMotionStore.start(daemonOnline)
  }, [daemonOnline])

  // Only stop when daemon actually goes offline — not on tab/page unmount.
  useEffect(() => {
    if (!daemonOnline && snapshot.active) stop()
  }, [daemonOnline, snapshot.active, stop])

  return {
    active: snapshot.active,
    loading: snapshot.loading,
    error: snapshot.error,
    poolSize: snapshot.poolSize,
    currentMove: snapshot.currentMove,
    start,
    stop,
  }
}
