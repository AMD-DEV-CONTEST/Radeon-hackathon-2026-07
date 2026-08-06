/**
 * React bindings for the module-level Reachy motion playback coordinator.
 */
import { useCallback, useMemo, useSyncExternalStore } from 'react'
import {
  reachyMotionPlaybackStore,
  type PlaybackEndedEvent,
  type PlaybackSource,
} from '../lib/reachyMotionPlaybackStore'

export type { PlaybackEndedEvent, PlaybackSource }

export function useReachyMotionPlayback() {
  const snapshot = useSyncExternalStore(
    reachyMotionPlaybackStore.subscribe,
    reachyMotionPlaybackStore.getSnapshot,
    reachyMotionPlaybackStore.getSnapshot,
  )

  const registerOnPlaybackEnded = useCallback(
    (cb: (event: PlaybackEndedEvent) => void) => reachyMotionPlaybackStore.registerOnPlaybackEnded(cb),
    [],
  )

  return useMemo(() => ({
    busy: snapshot.busy,
    currentMove: snapshot.currentMove,
    currentSource: snapshot.currentSource,
    isBusy: reachyMotionPlaybackStore.isBusy,
    playRecordedMove: reachyMotionPlaybackStore.playRecordedMove,
    playLocalMove: reachyMotionPlaybackStore.playLocalMove,
    registerOnPlaybackEnded,
  }), [
    snapshot.busy,
    snapshot.currentMove,
    snapshot.currentSource,
    registerOnPlaybackEnded,
  ])
}

/** @deprecated Provider is a no-op; playback store is module-level. Kept for compatibility. */
export function ReachyMotionPlaybackProvider({ children }: { children: React.ReactNode }) {
  return children
}
